"""Review queue for subscriptions detected in email.

Detections stay pending until the user acts. Approving one writes to the real
subscriptions table (create, or price-update when it matched a tracked
subscription) and records the change in the change log; dismissing marks it so
rescans don't resurface it.
"""
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import verify_token
from app.models import (
    AmountType,
    BillingCycle,
    Category,
    ChangeKind,
    DetectedSubscription,
    DetectionStatus,
    PaymentReminder,
    PaymentStatus,
    RecurrenceUnit,
    Subscription,
    UserPreference,
)
from app.routers.rates import conversion_for_storage
from app.routers.subscriptions import log_change, rebill, resolve_split
from app.services.recurrence import (
    Cadence,
    cadence_for,
    cadence_label,
    legacy_cycle_for,
    monthly_equivalent,
    utc_naive,
)
from app.services.trials import sync_trial_reminder, utcnow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/detected", tags=["detected"])


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _known_cadence(item, *, detection: bool = False) -> Cadence | None:
    if detection and str(_enum_value(getattr(item, "cadence_confidence", "unknown"))) == "unknown":
        return None
    unit = _enum_value(getattr(item, "interval_unit", None))
    count = getattr(item, "interval_count", None)
    if unit and count:
        try:
            return Cadence(str(unit), int(count))
        except (TypeError, ValueError):
            return None
    try:
        return cadence_for(item)
    except ValueError:
        return None


def _cadence_fields(item, *, detection: bool = False) -> dict:
    cadence = _known_cadence(item, detection=detection)
    return {
        "interval_unit": cadence.unit if cadence else None,
        "interval_count": cadence.count if cadence else None,
        "cadence_label": cadence_label(cadence.unit, cadence.count) if cadence else None,
    }


def _serialize(
    d: DetectedSubscription,
    tracked: Subscription | None = None,
    similar: Subscription | None = None,
) -> dict:
    detected_cadence = _cadence_fields(d, detection=True)
    tracked_cadence = _cadence_fields(tracked) if tracked else {
        "interval_unit": None,
        "interval_count": None,
        "cadence_label": None,
    }
    similar_cadence = _cadence_fields(similar) if similar else {
        "interval_unit": None,
        "interval_count": None,
        "cadence_label": None,
    }
    return {
        # For a price change, what the user currently pays and how it's split —
        # so the review card can show "you pay 320 of this" rather than making
        # them remember the arrangement.
        "current_amount": tracked.amount if tracked else None,
        "current_currency": tracked.currency if tracked else None,
        "current_full_amount": tracked.full_amount if tracked else None,
        "current_share_ratio": tracked.share_ratio if tracked else None,
        "current_split_mode": tracked.split_mode if tracked else None,
        "current_amount_type": _enum_value(tracked.amount_type) if tracked else None,
        "current_next_due": tracked.next_due.isoformat() if tracked and tracked.next_due else None,
        "current_interval_unit": tracked_cadence["interval_unit"],
        "current_interval_count": tracked_cadence["interval_count"],
        "current_cadence_label": tracked_cadence["cadence_label"],
        "id": str(d.id),
        "merchant": d.merchant,
        "sender_domain": d.sender_domain,
        "product_key": d.product_key or "",
        # What approving will do to the tracked subscription, so the button can
        # say so rather than leaving the user to guess.
        "current_name": tracked.name if tracked else None,
        "current_cycle": (tracked.cycle.value if hasattr(tracked.cycle, "value") else tracked.cycle)
            if tracked else None,
        "category": d.category.value if hasattr(d.category, "value") else d.category,
        # Do not leak the database-only monthly placeholder as if Gmail had
        # inferred it. Flexible clients use interval fields; older clients see
        # null and cannot accidentally present false certainty.
        "cycle": (
            d.cycle.value if hasattr(d.cycle, "value") else d.cycle
        ) if detected_cadence["interval_unit"] else None,
        **detected_cadence,
        "cadence_confidence": d.cadence_confidence,
        "cadence_evidence": d.cadence_evidence,
        "amount_type": _enum_value(d.amount_type),
        "amount": d.amount,
        "currency": d.currency,
        "previous_amount": d.previous_amount,
        "cancelled": d.cancelled,
        "confidence": d.confidence,
        "charge_count": d.charge_count,
        "trial_ends_at": d.trial_ends_at.isoformat() if d.trial_ends_at else None,
        "next_due": d.next_due.isoformat() if d.next_due else None,
        "due_date_confidence": d.due_date_confidence,
        "due_date_evidence": d.due_date_evidence,
        "existing_subscription_id": str(d.existing_subscription_id)
            if d.existing_subscription_id else None,
        # A subscription that looks like the same service under another name.
        # Surfaced as a choice, never applied automatically.
        "similar_subscription_id": str(d.similar_subscription_id)
            if d.similar_subscription_id else None,
        "similar_reason": d.similar_reason,
        "similar_name": similar.name if similar else None,
        "similar_amount": similar.amount if similar else None,
        "similar_currency": similar.currency if similar else None,
        "similar_full_amount": similar.full_amount if similar else None,
        "similar_share_ratio": similar.share_ratio if similar else None,
        "similar_split_mode": similar.split_mode if similar else None,
        "similar_cycle": (similar.cycle.value if hasattr(similar.cycle, "value") else similar.cycle)
            if similar else None,
        "similar_interval_unit": similar_cadence["interval_unit"],
        "similar_interval_count": similar_cadence["interval_count"],
        "similar_cadence_label": similar_cadence["cadence_label"],
        "detected_at": d.detected_at.isoformat() if d.detected_at else None,
    }


def _get_pending(
    db: Session,
    user_id: str,
    detection_id: UUID,
    *,
    for_update: bool = False,
) -> DetectedSubscription:
    query = db.query(DetectedSubscription).filter(
        DetectedSubscription.id == detection_id,
        DetectedSubscription.user_id == user_id,
    )
    if for_update:
        query = query.with_for_update()
    detection = query.first()
    if not detection:
        raise HTTPException(status_code=404, detail="Detection not found")
    if detection.status != DetectionStatus.pending:
        raise HTTPException(status_code=409, detail="Already resolved")
    return detection


@router.get("/")
def list_detections(
    status: DetectionStatus = DetectionStatus.pending,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Pending by default; pass status=dismissed to review what was rejected."""
    pending = db.query(DetectedSubscription).filter(
        DetectedSubscription.user_id == user_id,
        DetectedSubscription.status == status,
    ).order_by(DetectedSubscription.charge_count.desc()).all()

    wanted = {d.existing_subscription_id for d in pending if d.existing_subscription_id}
    wanted |= {d.similar_subscription_id for d in pending if d.similar_subscription_id}
    subs = {
        s.id: s for s in db.query(Subscription).filter(
            Subscription.user_id == user_id,
            Subscription.id.in_(wanted),
        ).all()
    } if wanted else {}

    return [
        _serialize(d, subs.get(d.existing_subscription_id), subs.get(d.similar_subscription_id))
        for d in pending
    ]


class ApproveOverrides(BaseModel):
    """The user can correct the detection before it becomes real."""
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False,
    )

    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: Category | None = None
    amount: float | None = Field(default=None, gt=0)
    interval_unit: RecurrenceUnit | None = None
    interval_count: int | None = Field(default=None, ge=1, le=1200)
    # Compatibility correction for clients that have not adopted flexible
    # intervals yet. It always becomes a unit/count pair before persistence.
    cycle: BillingCycle | None = None
    trial_ends_at: datetime | None = None
    next_due: datetime | None = None
    amount_type: AmountType | None = None
    # Shared bills: the receipt is the whole cost, but the user may only pay a
    # portion of it (rent split three ways, a household energy bill). Storing
    # the ratio rather than a corrected amount keeps future scans from reading
    # the difference as a price change.
    share_ratio: float | None = Field(default=None, gt=0, le=1)
    # An agreed uneven amount (rent split 320/320/410). Unlike a ratio this is
    # pinned: a later increase to the bill does not silently rescale it.
    share_amount: float | None = Field(default=None, gt=0)
    # The user's answer to "this looks like your existing X": the id to fold
    # this into, or None to add it as a separate subscription.
    replace_subscription_id: UUID | None = None

    @model_validator(mode="after")
    def validate_cadence_pair(self):
        if (self.interval_unit is None) != (self.interval_count is None):
            raise ValueError("Billing interval unit and count must be provided together")
        return self


def _approval_cadence(
    detection: DetectedSubscription,
    overrides: ApproveOverrides,
) -> Cadence:
    if overrides.interval_unit is not None and overrides.interval_count is not None:
        return Cadence(_enum_value(overrides.interval_unit), overrides.interval_count)
    if overrides.cycle is not None:
        return cadence_for(overrides.cycle)

    cadence = _known_cadence(detection, detection=True)
    if cadence is not None:
        return cadence
    raise HTTPException(
        status_code=422,
        detail=(
            "Choose how often this payment repeats before approving it. "
            "Gmail did not contain enough evidence to infer the frequency safely."
        ),
    )


def apply_approval(
    detection_id: UUID,
    overrides: ApproveOverrides,
    user_id: str,
    db: Session,
    *,
    commit: bool = False,
) -> dict:
    """Apply one reviewed Gmail finding inside the caller's transaction.

    Both the HTTP endpoint and assistant-confirmation executor use this exact
    mutation path. ``commit=False`` lets the assistant atomically persist the
    subscription, detection resolution, and AgentAction status in one commit.
    Ownership checks and row locks remain here so internal callers cannot
    accidentally bypass them.
    """
    # PostgreSQL serializes competing approvals for the same review row. The
    # second request wakes after the first commit and gets a clean 409 instead
    # of creating a duplicate subscription.
    detection = _get_pending(db, user_id, detection_id, for_update=True)

    name = (overrides.name or detection.merchant).strip()
    if not name:
        raise HTTPException(status_code=422, detail="Enter a name for this payment")
    cadence = _approval_cadence(detection, overrides)
    cycle = legacy_cycle_for(cadence.unit, cadence.count)
    category = overrides.category or detection.category
    amount_type = _enum_value(overrides.amount_type or detection.amount_type or AmountType.fixed)

    # Either an automatic price-change match, or the subscription the user chose
    # to replace when told this looks like a service they already track.
    target_id = overrides.replace_subscription_id or detection.existing_subscription_id

    # The receipt is the full bill. If the user only pays part of it, `amount`
    # becomes their share and the full cost is kept for future scan comparisons.
    billed = overrides.amount if overrides.amount is not None else detection.amount
    if billed <= 0 and not (detection.cancelled and target_id):
        raise HTTPException(
            status_code=422,
            detail="Enter the recurring price that will be charged after this trial",
        )
    trial_override_supplied = "trial_ends_at" in overrides.model_fields_set
    trial_supplied = detection.trial_ends_at is not None or trial_override_supplied
    trial_end = overrides.trial_ends_at \
        if trial_override_supplied else detection.trial_ends_at
    trial_end = utc_naive(trial_end) if trial_end else None
    if trial_end and trial_end.date() < utcnow().date():
        raise HTTPException(status_code=422, detail="The trial end date has already passed")

    next_due_override_supplied = "next_due" in overrides.model_fields_set
    next_due_supplied = detection.next_due is not None or next_due_override_supplied
    next_due = overrides.next_due \
        if next_due_override_supplied else detection.next_due
    next_due = utc_naive(next_due) if next_due else None
    if trial_end:
        next_due = trial_end
        next_due_supplied = True
    if next_due and next_due.date() < utcnow().date():
        if target_id and not next_due_override_supplied:
            # A receipt may describe a charge that has already happened. When
            # updating a tracked payment, stale inferred evidence must never
            # erase or reject the user's newer saved schedule. An explicit
            # correction remains authoritative and is still validated.
            next_due = None
            next_due_supplied = False
        else:
            raise HTTPException(status_code=422, detail="The next due date has already passed")

    if target_id:
        sub = db.query(Subscription).filter(
            Subscription.id == target_id,
            Subscription.user_id == user_id,
        ).with_for_update().first()
        if not sub:
            raise HTTPException(status_code=404, detail="Tracked subscription no longer exists")

        before = monthly_equivalent(sub.amount, sub)
        before_currency = sub.currency
        # Cancellation notices often contain no amount. An exact/user-confirmed
        # match can safely retain the bill already tracked instead of making
        # cancellation impossible to approve.
        if billed <= 0:
            billed = sub.full_amount if sub.full_amount is not None else sub.amount
        split = resolve_split(billed, overrides.share_ratio, overrides.share_amount)
        # Keep the existing split unless this approval sets a new one. An equal
        # split scales with the new bill; a fixed amount stays put, because who
        # absorbs an increase is for the housemates to agree, not us to assume.
        if overrides.share_ratio is None and overrides.share_amount is None:
            split = rebill(sub, billed)
        sub.amount = split.amount
        sub.full_amount = split.full_amount
        sub.share_ratio = split.share_ratio
        sub.split_mode = split.split_mode
        # A detection usually knows the product better than an old generic name
        # ("Apple" -> "Apple Music"), so adopt the better name unless the user
        # gave one explicitly.
        if overrides.name:
            sub.name = overrides.name
        elif detection.merchant and len(detection.merchant) > len(sub.name):
            sub.name = detection.merchant
        sub.category = category
        sub.cycle = cycle
        sub.interval_unit = cadence.unit
        sub.interval_count = cadence.count
        sub.amount_type = amount_type
        sub.currency = detection.currency.upper()
        preference = db.query(UserPreference).filter(
            UserPreference.user_id == user_id,
        ).first()
        base = preference.base_currency if preference else "AUD"
        # Do not carry a stale or browser-supplied conversion from the former
        # amount/currency. All mutation paths use the shared server snapshot.
        sub.converted_amount, sub.exchange_rate, _quality = conversion_for_storage(
            sub.amount, sub.currency, base, db,
        )
        if trial_supplied:
            sub.trial_ends_at = trial_end
        if next_due_supplied:
            sub.next_due = next_due
        # Bind the subscription to its source so later scans recognise it even
        # if the analyzer words the merchant differently.
        sub.source_domain = detection.sender_domain
        sub.source_key = detection.product_key or sub.source_key
        if detection.cancelled:
            sub.is_active = False
            sub.status = PaymentStatus.cancelled.value
            sub.next_due = None
            sub.paused_until = None
            db.query(PaymentReminder).filter(
                PaymentReminder.user_id == user_id,
                PaymentReminder.subscription_id == sub.id,
            ).update({PaymentReminder.is_active: False}, synchronize_session=False)
        else:
            if detection.charge_count > 0 and not sub.is_active:
                # A successful new charge is explicit evidence that a previously
                # inactive tracked subscription has resumed.
                sub.is_active = True
                sub.status = PaymentStatus.active.value
                sub.paused_until = None
                sub.cancellation_effective_at = None
                sub.recurrence_end_at = None
            if trial_supplied:
                sync_trial_reminder(db, sub)
            elif sub.trial_ends_at and detection.charge_count > 0:
                # A later successful charge is evidence that the trial converted.
                # Clear its automatic cancellation reminder instead of leaving an
                # already-paid trial permanently overdue on the dashboard.
                sub.trial_ends_at = None
                sync_trial_reminder(db, sub)
        after = monthly_equivalent(sub.amount, sub)
        if sub.currency != before_currency:
            log_change(
                db, sub, ChangeKind.removed, before, None,
                currency=before_currency,
            )
            log_change(db, sub, ChangeKind.added, None, after)
        elif after != before:
            log_change(db, sub, ChangeKind.price_change, before, after)
    else:
        split = resolve_split(billed, overrides.share_ratio, overrides.share_amount)
        preference = db.query(UserPreference).filter(
            UserPreference.user_id == user_id,
        ).first()
        base = preference.base_currency if preference else "AUD"
        currency = detection.currency.upper()
        converted, exchange_rate, _quality = conversion_for_storage(
            split.amount, currency, base, db,
        )
        sub = Subscription(
            user_id=user_id,
            name=name,
            category=category,
            amount=split.amount,
            full_amount=split.full_amount,
            share_ratio=split.share_ratio,
            split_mode=split.split_mode,
            source_domain=detection.sender_domain,
            source_key=detection.product_key or None,
            currency=currency,
            exchange_rate=exchange_rate,
            converted_amount=converted,
            cycle=cycle,
            interval_unit=cadence.unit,
            interval_count=cadence.count,
            next_due=None if detection.cancelled else next_due,
            trial_ends_at=trial_end,
            status=(
                PaymentStatus.cancelled.value
                if detection.cancelled else PaymentStatus.active.value
            ),
            amount_type=amount_type,
            is_active=not detection.cancelled,
        )
        db.add(sub)
        db.flush()
        if trial_end and sub.is_active:
            sync_trial_reminder(db, sub)
        log_change(db, sub, ChangeKind.added, None,
                   monthly_equivalent(split.amount, cadence.unit, cadence.count))

    detection.status = DetectionStatus.approved
    detection.resolved_at = utcnow()
    if commit:
        db.commit()
    else:
        # Allocate ids and surface constraint errors while preserving the
        # surrounding transaction for the caller.
        db.flush()

    return {
        "approved": True,
        "detection_id": str(detection.id),
        "subscription_id": str(sub.id),
    }


@router.post("/{detection_id}/approve")
def approve(
    detection_id: UUID,
    overrides: ApproveOverrides,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    result = apply_approval(
        detection_id,
        overrides,
        user_id,
        db,
        commit=True,
    )
    logger.info("Detection approved", extra={"user_id": user_id})
    return result


@router.post("/{detection_id}/dismiss")
def dismiss(
    detection_id: UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    detection = _get_pending(db, user_id, detection_id)
    detection.status = DetectionStatus.dismissed
    detection.resolved_at = datetime.utcnow()
    db.commit()
    return {"dismissed": True}


@router.post("/{detection_id}/restore")
def restore(
    detection_id: UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Put a dismissed detection back in the queue — dismissing by mistake
    shouldn't mean losing it until the next scan (which deliberately skips
    dismissed merchants, so it would never come back on its own)."""
    detection = db.query(DetectedSubscription).filter(
        DetectedSubscription.id == detection_id,
        DetectedSubscription.user_id == user_id,
    ).first()
    if not detection:
        raise HTTPException(status_code=404, detail="Detection not found")
    if detection.status != DetectionStatus.dismissed:
        raise HTTPException(status_code=409, detail="Only dismissed detections can be restored")

    detection.status = DetectionStatus.pending
    detection.resolved_at = None
    db.commit()
    return {"restored": True}
