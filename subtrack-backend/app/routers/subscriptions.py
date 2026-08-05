from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import NamedTuple, Optional
from datetime import datetime
from uuid import UUID
from app.database import get_db
from app.models import (
    AgentResearchCache, AmountType, BillingCycle, Category, ChangeKind, DetectedSubscription,
    PaymentReminder, PaymentStatus, RecurrenceUnit, SpendingType, Subscription,
    SubscriptionChange, UserPreference,
)
from app.middleware.auth import verify_token
from app.routers.rates import conversion_for_storage
from app.services.recurrence import (
    Cadence,
    annual_equivalent,
    cadence_for,
    cadence_label,
    effective_status,
    forecast_end_for,
    legacy_cycle_for,
    monthly_equivalent,
    project_next_occurrence,
    utc_naive,
)
from app.services.trials import sync_trial_reminder, utcnow
from app.services.duplicates import (
    DUPLICATE_CACHE_SECONDS,
    DUPLICATE_MODEL_LIMIT,
    _duplicate_cache,
    _duplicate_cache_lock,
    delete_duplicate_dismissals_for_subscription,
    duplicate_suggestions,
    persist_duplicate_dismissal,
)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

def log_change(db: Session, sub: Subscription, kind: ChangeKind,
               old_monthly: float | None, new_monthly: float | None,
               *, currency: str | None = None):
    db.add(SubscriptionChange(
        user_id=sub.user_id,
        subscription_id=sub.id,
        name=sub.name,
        kind=kind,
        old_monthly=old_monthly,
        new_monthly=new_monthly,
        currency=currency or sub.currency,
    ))


def subscription_payload(sub: Subscription) -> dict:
    """Stable API shape with backend-owned financial equivalents."""
    cadence = cadence_for(sub)
    status = effective_status(sub)
    next_expected_at = None
    next_expected_source = "inactive"
    if status in {PaymentStatus.active.value, PaymentStatus.cancelling.value}:
        next_expected_at, next_expected_source = project_next_occurrence(
            sub.next_due,
            sub,
            utcnow(),
            recurrence_end_at=forecast_end_for(sub),
        )
    elif status == PaymentStatus.paused.value:
        if sub.paused_until:
            next_expected_at, next_expected_source = project_next_occurrence(
                sub.next_due,
                sub,
                max(utcnow(), utc_naive(sub.paused_until)),
                recurrence_end_at=forecast_end_for(sub),
            )
        else:
            next_expected_source = "paused_without_resume"
    return {
        "id": str(sub.id),
        "user_id": sub.user_id,
        "name": sub.name,
        "category": sub.category.value if hasattr(sub.category, "value") else sub.category,
        "amount": sub.amount,
        "full_amount": sub.full_amount,
        "share_ratio": sub.share_ratio,
        "split_mode": sub.split_mode,
        "currency": sub.currency,
        "exchange_rate": sub.exchange_rate,
        "converted_amount": sub.converted_amount,
        "cycle": sub.cycle.value if hasattr(sub.cycle, "value") else sub.cycle,
        "interval_unit": cadence.unit,
        "interval_count": cadence.count,
        "cadence_label": cadence_label(cadence.unit, cadence.count),
        # Preserve calculation precision in the API so totals do not accumulate
        # per-row rounding error. Clients round only when formatting money.
        "monthly_equivalent": monthly_equivalent(sub.amount, sub),
        "yearly_equivalent": annual_equivalent(sub.amount, sub),
        "next_due": sub.next_due.isoformat() if sub.next_due else None,
        "next_expected_at": (
            next_expected_at.isoformat() if next_expected_at else None
        ),
        "next_expected_source": next_expected_source,
        "recurrence_end_at": (
            sub.recurrence_end_at.isoformat() if sub.recurrence_end_at else None
        ),
        "trial_ends_at": sub.trial_ends_at.isoformat() if sub.trial_ends_at else None,
        "status": status,
        "paused_until": sub.paused_until.isoformat() if sub.paused_until else None,
        "cancellation_effective_at": (
            sub.cancellation_effective_at.isoformat()
            if sub.cancellation_effective_at else None
        ),
        "amount_type": sub.amount_type or AmountType.fixed.value,
        "spending_type": sub.spending_type or SpendingType.unspecified.value,
        "is_active": status not in {PaymentStatus.cancelled.value, PaymentStatus.ended.value},
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
    }


def retarget_detection_links(
    db: Session,
    user_id: str,
    source_id: UUID,
    target_id: UUID | None,
) -> None:
    """Keep pending Gmail review rows valid when a tracked row changes identity.

    Detection links are intentionally not database foreign keys because a
    review finding survives changes to the tracked list.  That means every
    delete/merge path must repair the optional links explicitly.
    """
    rows = db.query(DetectedSubscription).filter(
        DetectedSubscription.user_id == user_id,
        (
            (DetectedSubscription.existing_subscription_id == source_id)
            | (DetectedSubscription.similar_subscription_id == source_id)
        ),
    ).all()
    for row in rows:
        if row.existing_subscription_id == source_id:
            row.existing_subscription_id = target_id
        if row.similar_subscription_id == source_id:
            row.similar_subscription_id = target_id
        # A merge can collapse two different hints onto the same target.  The
        # exact tracked match wins; retaining the same row as a second
        # "possible duplicate" would force a meaningless choice in Review.
        if (
            row.existing_subscription_id is not None
            and row.similar_subscription_id == row.existing_subscription_id
        ):
            row.similar_subscription_id = None
            row.similar_reason = None

class Split(NamedTuple):
    amount: float                  # what this user pays — stored as `amount`
    full_amount: Optional[float]   # the whole bill, or None when unsplit
    share_ratio: float
    split_mode: str                # full | ratio | fixed


def resolve_split(billed: float, share_ratio: Optional[float] = None,
                  share_amount: Optional[float] = None) -> Split:
    """Work out the user's portion of a bill.

    `share_amount` (an agreed uneven amount, e.g. 320 of a 320/320/410 rent)
    takes precedence over `share_ratio` (an equal split). They behave
    differently when the bill later changes — see Subscription.split_mode.
    """
    if share_amount is not None and 0 < share_amount < billed:
        return Split(round(share_amount, 2), billed, share_amount / billed, "fixed")
    if share_ratio is not None and 0 < share_ratio < 1.0:
        return Split(round(billed * share_ratio, 2), billed, share_ratio, "ratio")
    return Split(billed, None, 1.0, "full")


def rebill(sub: Subscription, new_billed: float) -> Split:
    """Re-apply an existing split after the underlying bill changed.

    An equal split scales with the bill. A fixed amount does not — the user
    agreed to pay that figure, and who absorbs an increase is theirs to decide.
    """
    if sub.split_mode == "ratio" and sub.share_ratio:
        return resolve_split(new_billed, share_ratio=sub.share_ratio)
    if sub.split_mode == "fixed":
        return Split(sub.amount, new_billed, sub.amount / new_billed if new_billed else 1.0, "fixed")
    return resolve_split(new_billed)


class SubscriptionCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False,
    )

    name: str = Field(min_length=1, max_length=160)
    category: Category
    amount: float = Field(gt=0)
    currency: str = Field(default="AUD", min_length=3, max_length=3)
    exchange_rate: float = Field(default=1.0, gt=0)
    converted_amount: Optional[float] = Field(default=None, ge=0)
    # ``cycle`` remains accepted for clients from the previous release.
    cycle: Optional[BillingCycle] = None
    interval_unit: Optional[RecurrenceUnit] = None
    interval_count: Optional[int] = Field(default=None, ge=1, le=1200)
    next_due: Optional[datetime] = None
    recurrence_end_at: Optional[datetime] = None
    trial_ends_at: Optional[datetime] = None
    status: PaymentStatus = PaymentStatus.active
    paused_until: Optional[datetime] = None
    cancellation_effective_at: Optional[datetime] = None
    amount_type: AmountType = AmountType.fixed
    spending_type: SpendingType = SpendingType.unspecified
    is_active: bool = True
    # Shared bills: send the full cost and the caller's portion (e.g. 1/3).
    # `amount` is then derived and represents only what this user pays.
    full_amount: Optional[float] = Field(default=None, gt=0)
    share_ratio: Optional[float] = Field(default=None, gt=0, le=1)
    share_amount: Optional[float] = Field(default=None, gt=0)

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str) -> str:
        value = value.upper()
        if not value.isalpha():
            raise ValueError("Currency must be a three-letter ISO code")
        return value

    @model_validator(mode="after")
    def validate_cadence(self):
        if (self.interval_unit is None) != (self.interval_count is None):
            raise ValueError("Billing interval unit and count must be provided together")
        if self.interval_unit is None and self.cycle is None:
            raise ValueError("A billing interval is required")
        if self.status == PaymentStatus.cancelling and self.cancellation_effective_at is None:
            raise ValueError("A cancelling payment needs its cancellation effective date")
        if (
            self.status == PaymentStatus.paused
            and self.paused_until is not None
            and utc_naive(self.paused_until).date() <= utcnow().date()
        ):
            raise ValueError("The pause-until date must be in the future")
        return self

class SubscriptionUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False,
    )

    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    category: Optional[Category] = None
    amount: Optional[float] = Field(default=None, gt=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    exchange_rate: Optional[float] = Field(default=None, gt=0)
    converted_amount: Optional[float] = Field(default=None, ge=0)
    cycle: Optional[BillingCycle] = None
    interval_unit: Optional[RecurrenceUnit] = None
    interval_count: Optional[int] = Field(default=None, ge=1, le=1200)
    next_due: Optional[datetime] = None
    recurrence_end_at: Optional[datetime] = None
    trial_ends_at: Optional[datetime] = None
    status: Optional[PaymentStatus] = None
    paused_until: Optional[datetime] = None
    cancellation_effective_at: Optional[datetime] = None
    amount_type: Optional[AmountType] = None
    spending_type: Optional[SpendingType] = None
    is_active: Optional[bool] = None
    full_amount: Optional[float] = Field(default=None, gt=0)
    share_ratio: Optional[float] = Field(default=None, gt=0, le=1)
    share_amount: Optional[float] = Field(default=None, gt=0)

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.upper()
        if not value.isalpha():
            raise ValueError("Currency must be a three-letter ISO code")
        return value

    @model_validator(mode="after")
    def validate_cadence(self):
        supplied = self.model_fields_set
        if ("interval_unit" in supplied) != ("interval_count" in supplied):
            raise ValueError("Billing interval unit and count must be updated together")
        if "interval_unit" in supplied and (
            self.interval_unit is None or self.interval_count is None
        ):
            raise ValueError("Billing interval unit and count cannot be cleared")
        return self


class EquivalencePreview(BaseModel):
    """Minimal server-owned recurrence calculation for add/edit previews."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    amount: float = Field(gt=0)
    interval_unit: RecurrenceUnit
    interval_count: int = Field(ge=1, le=1200)


@router.post("/equivalents")
def preview_equivalents(
    data: EquivalencePreview,
    user_id: str = Depends(verify_token),
):
    del user_id  # Authentication protects the endpoint; no user data is read.
    unit = data.interval_unit.value
    return {
        "amount": data.amount,
        "interval_unit": unit,
        "interval_count": data.interval_count,
        "cadence_label": cadence_label(unit, data.interval_count),
        "monthly_equivalent": monthly_equivalent(
            data.amount, unit, data.interval_count,
        ),
        "yearly_equivalent": annual_equivalent(
            data.amount, unit, data.interval_count,
        ),
        "normalization_convention": "365 days per year; 52 weeks per year",
    }

@router.get("/")
def get_subscriptions(
    include_inactive: bool = False,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    query = db.query(Subscription).filter(Subscription.user_id == user_id)
    if not include_inactive:
        query = query.filter(Subscription.is_active == True)  # noqa: E712
    rows = query.order_by(Subscription.name).all()
    if not include_inactive:
        rows = [
            sub for sub in rows
            if effective_status(sub) not in {
                PaymentStatus.cancelled.value, PaymentStatus.ended.value,
            }
        ]
    return [subscription_payload(sub) for sub in rows]


@router.get("/forecast")
def get_upcoming_forecast(
    days: int = Query(default=30, ge=1, le=730),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Exact projected occurrences for the dashboard, not prorated averages."""
    # The assistant and UI deliberately share this implementation so a weekly
    # payment appears once per expected charge in both places.
    from app.agent.finance import upcoming_charges

    return upcoming_charges(db, user_id, days=days)

@router.get("/changes")
def get_changes(
    days: int = Query(default=30, ge=1, le=730),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """Changes in the last `days`, newest first — what moved and by how much."""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)
    changes = db.query(SubscriptionChange).filter(
        SubscriptionChange.user_id == user_id,
        SubscriptionChange.changed_at >= cutoff
    ).order_by(SubscriptionChange.changed_at.desc()).all()

    return [
        {
            "id": str(c.id),
            "subscription_id": str(c.subscription_id),
            "name": c.name,
            "kind": c.kind.value if hasattr(c.kind, "value") else c.kind,
            "old_monthly": c.old_monthly,
            "new_monthly": c.new_monthly,
            "delta": (c.new_monthly or 0) - (c.old_monthly or 0),
            "currency": c.currency,
            "changed_at": c.changed_at.isoformat() if c.changed_at else None,
        }
        for c in changes
    ]

@router.post("/")
def create_subscription(
    data: SubscriptionCreate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    fields = data.model_dump()
    # Accepted for rolling-client compatibility, but never trusted. The server
    # derives stored conversion data from its shared rate snapshot below.
    fields.pop("exchange_rate", None)
    fields.pop("converted_amount", None)
    unit = fields.pop("interval_unit")
    count = fields.pop("interval_count")
    cycle = fields.pop("cycle")
    cadence = Cadence(unit.value, count) if unit and count else cadence_for(cycle)
    fields["interval_unit"] = cadence.unit
    fields["interval_count"] = cadence.count
    fields["cycle"] = legacy_cycle_for(cadence.unit, cadence.count)
    for enum_field in ("status", "amount_type", "spending_type"):
        value = fields.get(enum_field)
        fields[enum_field] = value.value if hasattr(value, "value") else value
    # During the rolling-deploy window an older frontend knows only
    # ``is_active``. Honour that legacy value unless the new lifecycle status
    # was explicitly submitted; otherwise an old inactive record would be
    # silently reactivated on creation.
    if "status" not in data.model_fields_set and "is_active" in data.model_fields_set:
        fields["status"] = (
            PaymentStatus.active.value
            if fields["is_active"] else PaymentStatus.cancelled.value
        )
    fields["is_active"] = fields["status"] not in {
        PaymentStatus.cancelled.value,
        PaymentStatus.ended.value,
    }
    trial_end = fields.get("trial_ends_at")
    if trial_end and utc_naive(trial_end).date() < utcnow().date():
        raise HTTPException(status_code=422, detail="The trial end date has already passed")
    if trial_end and fields.get("next_due") is None:
        fields["next_due"] = trial_end
    recurrence_end = fields.get("recurrence_end_at")
    if recurrence_end and fields.get("next_due") and (
        utc_naive(recurrence_end).date() < utc_naive(fields["next_due"]).date()
    ):
        raise HTTPException(
            status_code=422,
            detail="The recurrence end cannot be before the next payment",
        )
    # The caller sends the whole bill plus how it's split; `amount` ends up as
    # this user's portion so every downstream total needs no special case.
    billed = fields.pop("full_amount") or fields["amount"]
    split = resolve_split(billed, fields.pop("share_ratio"), fields.pop("share_amount"))
    fields["amount"] = split.amount
    preference = db.query(UserPreference).filter(
        UserPreference.user_id == user_id,
    ).first()
    base_currency = preference.base_currency if preference else "AUD"
    converted, exchange_rate, _quality = conversion_for_storage(
        split.amount, fields["currency"], base_currency, db,
    )
    fields["converted_amount"] = converted
    fields["exchange_rate"] = exchange_rate

    sub = Subscription(**fields, user_id=user_id,
                       full_amount=split.full_amount,
                       share_ratio=split.share_ratio,
                       split_mode=split.split_mode)
    db.add(sub)
    db.flush()   # need sub.id before logging the change
    if sub.trial_ends_at and sub.is_active:
        sync_trial_reminder(db, sub)
    log_change(db, sub, ChangeKind.added, None, monthly_equivalent(sub.amount, sub))
    db.commit()
    db.refresh(sub)
    return subscription_payload(sub)

@router.patch("/{sub_id}")
def update_subscription(
    sub_id: UUID,
    data: SubscriptionUpdate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    sub = db.query(Subscription).filter(
        Subscription.id == sub_id,
        Subscription.user_id == user_id
    ).with_for_update().first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    before = monthly_equivalent(sub.amount, sub)
    before_currency = sub.currency

    supplied = data.model_dump(exclude_unset=True)
    supplied.pop("exchange_rate", None)
    supplied.pop("converted_amount", None)
    conversion_changed = bool({
        "amount", "currency", "full_amount", "share_ratio", "share_amount",
    } & data.model_fields_set)
    requested_unit = supplied.pop("interval_unit", None)
    requested_count = supplied.pop("interval_count", None)
    requested_cycle = supplied.pop("cycle", None)
    if requested_unit is not None and requested_count is not None:
        cadence = Cadence(
            requested_unit.value if hasattr(requested_unit, "value") else requested_unit,
            requested_count,
        )
        sub.interval_unit = cadence.unit
        sub.interval_count = cadence.count
        sub.cycle = legacy_cycle_for(cadence.unit, cadence.count)
    elif requested_cycle is not None:
        # A cached pre-cadence client submits its displayed cycle on every edit.
        # Preserve a custom cadence if that compatibility value did not change.
        if sub.interval_unit is None or requested_cycle != sub.cycle:
            cadence = cadence_for(requested_cycle)
            sub.interval_unit = cadence.unit
            sub.interval_count = cadence.count
            sub.cycle = requested_cycle
    trial_changed = "trial_ends_at" in supplied
    trial_end = supplied.pop("trial_ends_at", None)
    if trial_end and utc_naive(trial_end).date() < utcnow().date():
        raise HTTPException(status_code=422, detail="The trial end date has already passed")
    # Existing update semantics intentionally ignore null for ordinary fields;
    # trial metadata is the exception because unchecking "free trial" must be
    # able to clear the saved date.
    clearable_dates = {
        "next_due", "recurrence_end_at", "paused_until", "cancellation_effective_at",
    }
    fields = {
        key: value for key, value in supplied.items()
        if value is not None or key in clearable_dates
    }
    # A split can be edited independently of the amount, so resolve against
    # whatever the caller didn't send.
    if {"full_amount", "share_ratio", "share_amount"} & fields.keys():
        billed = fields.pop("full_amount", None) or fields.get("amount") \
            or sub.full_amount or sub.amount
        split = resolve_split(billed, fields.pop("share_ratio", None),
                              fields.pop("share_amount", None))
        fields["amount"] = split.amount
        sub.full_amount = split.full_amount
        sub.share_ratio = split.share_ratio
        sub.split_mode = split.split_mode

    for key, value in fields.items():
        if hasattr(value, "value"):
            value = value.value
        setattr(sub, key, value)

    if "status" in fields:
        sub.is_active = sub.status not in {
            PaymentStatus.cancelled.value,
            PaymentStatus.ended.value,
        }
    elif "is_active" in fields:
        sub.status = (
            PaymentStatus.active.value if fields["is_active"]
            else PaymentStatus.cancelled.value
        )

    if sub.recurrence_end_at and sub.next_due and (
        utc_naive(sub.recurrence_end_at).date() < utc_naive(sub.next_due).date()
    ):
        raise HTTPException(
            status_code=422,
            detail="The recurrence end cannot be before the next payment",
        )
    if sub.status == PaymentStatus.cancelling.value and not sub.cancellation_effective_at:
        raise HTTPException(
            status_code=422,
            detail="A cancelling payment needs its cancellation effective date",
        )
    if (
        sub.status == PaymentStatus.paused.value
        and sub.paused_until is not None
        and utc_naive(sub.paused_until).date() <= utcnow().date()
    ):
        raise HTTPException(
            status_code=422,
            detail="The pause-until date must be in the future",
        )

    if trial_changed:
        sub.trial_ends_at = trial_end
        if trial_end and "next_due" not in supplied:
            sub.next_due = trial_end
        sync_trial_reminder(db, sub)

    if conversion_changed:
        preference = db.query(UserPreference).filter(
            UserPreference.user_id == user_id,
        ).first()
        base_currency = preference.base_currency if preference else "AUD"
        sub.converted_amount, sub.exchange_rate, _quality = conversion_for_storage(
            sub.amount, sub.currency, base_currency, db,
        )

    if not sub.is_active or sub.status in {
        PaymentStatus.cancelled.value,
        PaymentStatus.ended.value,
    }:
        db.query(PaymentReminder).filter(
            PaymentReminder.user_id == user_id,
            PaymentReminder.subscription_id == sub.id,
        ).update({PaymentReminder.is_active: False}, synchronize_session=False)

    after = monthly_equivalent(sub.amount, sub)
    if sub.currency != before_currency:
        # A single change row has only one currency column, so representing a
        # cross-currency edit as an ordinary price delta would compare unlike
        # units. Two balanced events preserve an auditable history and let
        # financial summaries convert each side independently.
        log_change(
            db, sub, ChangeKind.removed, before, None,
            currency=before_currency,
        )
        log_change(db, sub, ChangeKind.added, None, after)
    elif after != before:
        log_change(db, sub, ChangeKind.price_change, before, after)

    db.commit()
    db.refresh(sub)
    return subscription_payload(sub)

@router.get("/duplicates")
def get_duplicates(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """Pairs in the user's own list that look like the same service.

    Detection can produce "Claude" and "Anthropic (Claude)" as separate rows,
    which quietly double-counts the cost. Suggestions only — merging is the
    user's call.
    """
    try:
        subs, pairs = duplicate_suggestions(db, user_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    def brief(s):
        cadence = cadence_for(s)
        return {
            "id": str(s.id), "name": s.name, "amount": s.amount,
            "currency": s.currency,
            "cycle": s.cycle.value if hasattr(s.cycle, "value") else s.cycle,
            "interval_unit": cadence.unit,
            "interval_count": cadence.count,
            "cadence_label": cadence_label(cadence.unit, cadence.count),
        }

    return [
        {"keep": brief(subs[k]), "merge": brief(subs[m]), "reason": reason}
        for k, m, reason in pairs
    ]


class DismissDuplicateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription_id: UUID
    possible_duplicate_id: UUID

    @model_validator(mode="after")
    def distinct_records(self):
        if self.subscription_id == self.possible_duplicate_id:
            raise ValueError("A payment cannot be compared with itself")
        return self


@router.post("/duplicates/dismiss")
def dismiss_duplicate_suggestion(
    body: DismissDuplicateRequest,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Remember that two owned tracked records are intentionally distinct."""
    ids = [body.subscription_id, body.possible_duplicate_id]
    owned = db.query(Subscription.id).filter(
        Subscription.user_id == user_id,
        Subscription.id.in_(ids),
    ).all()
    if len(owned) != 2:
        # Do not reveal whether either UUID belongs to another account.
        raise HTTPException(status_code=404, detail="Recurring payment not found")

    row, created = persist_duplicate_dismissal(
        db,
        user_id,
        body.subscription_id,
        body.possible_duplicate_id,
    )
    db.commit()
    return {
        "dismissed": True,
        "already_dismissed": not created,
        "subscription_ids": [
            str(row.subscription_a_id),
            str(row.subscription_b_id),
        ],
    }


class MergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    into: UUID


@router.post("/{sub_id}/merge")
def merge_subscription(
    sub_id: UUID,
    body: MergeRequest,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """Fold one subscription into another, keeping the target's own details.

    History is reassigned rather than deleted so the change log stays intact.
    """
    if sub_id == body.into:
        raise HTTPException(status_code=400, detail="Cannot merge a subscription into itself")

    locked = {
        row.id: row for row in db.query(Subscription).filter(
            Subscription.user_id == user_id,
            Subscription.id.in_([sub_id, body.into]),
        ).order_by(Subscription.id).with_for_update().all()
    }
    source, target = locked.get(sub_id), locked.get(body.into)
    if not source or not target:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # Keep the source's source_key if the target has none, so future scans can
    # still recognise the merged subscription.
    if not target.source_key and source.source_key:
        target.source_key = source.source_key
        target.source_domain = source.source_domain

    db.query(SubscriptionChange).filter(
        SubscriptionChange.subscription_id == source.id
    ).update({SubscriptionChange.subscription_id: target.id})

    # Reminders belong to the recurring commitment, not the display row. Keep
    # them alive when duplicate records are folded together.
    target_reminders = db.query(PaymentReminder).filter(
        PaymentReminder.user_id == user_id,
        PaymentReminder.subscription_id == target.id,
        PaymentReminder.is_active == True,  # noqa: E712
    ).all()
    existing_keys = {
        (item.kind, item.days_before, item.target_date) for item in target_reminders
    }
    source_reminders = db.query(PaymentReminder).filter(
        PaymentReminder.user_id == user_id,
        PaymentReminder.subscription_id == source.id,
    ).all()
    for reminder in source_reminders:
        key = (reminder.kind, reminder.days_before, reminder.target_date)
        if reminder.is_active and key in existing_keys:
            db.delete(reminder)
        else:
            reminder.subscription_id = target.id
            if reminder.is_active:
                existing_keys.add(key)

    retarget_detection_links(db, user_id, source.id, target.id)
    # Cached market research is fingerprinted to the exact source record. It
    # is no longer meaningful after a merge and should not outlive that row.
    db.query(AgentResearchCache).filter(
        AgentResearchCache.user_id == user_id,
        AgentResearchCache.subscription_id == source.id,
    ).delete(synchronize_session=False)
    delete_duplicate_dismissals_for_subscription(db, user_id, source.id)
    db.delete(source)
    db.commit()
    db.refresh(target)
    return {"merged": True, "into": str(target.id), "name": target.name}


@router.delete("/{sub_id}")
def delete_subscription(
    sub_id: UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    sub = db.query(Subscription).filter(
        Subscription.id == sub_id,
        Subscription.user_id == user_id
    ).with_for_update().first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    log_change(db, sub, ChangeKind.removed, monthly_equivalent(sub.amount, sub), None)
    db.query(PaymentReminder).filter(
        PaymentReminder.user_id == user_id,
        PaymentReminder.subscription_id == sub.id,
    ).delete(synchronize_session=False)
    retarget_detection_links(db, user_id, sub.id, None)
    db.query(AgentResearchCache).filter(
        AgentResearchCache.user_id == user_id,
        AgentResearchCache.subscription_id == sub.id,
    ).delete(synchronize_session=False)
    delete_duplicate_dismissals_for_subscription(db, user_id, sub.id)
    db.delete(sub)
    db.commit()
    return {"message": "Deleted successfully"}
