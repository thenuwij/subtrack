"""Review queue for subscriptions detected in email.

Detections stay pending until the user acts. Approving one writes to the real
subscriptions table (create, or price-update when it matched a tracked
subscription) and records the change in the change log; dismissing marks it so
rescans don't resurface it.
"""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import verify_token
from app.models import (
    BillingCycle,
    Category,
    ChangeKind,
    DetectedSubscription,
    DetectionStatus,
    Subscription,
    PaymentReminder,
    UserPreference,
)
from app.routers.subscriptions import (log_change, monthly_equivalent, rebill,
                                       resolve_split)
from app.services.schedules import utc_naive
from app.services.trials import sync_trial_reminder, utcnow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/detected", tags=["detected"])


def _serialize(d: DetectedSubscription, tracked: Optional[Subscription] = None,
               similar: Optional[Subscription] = None) -> dict:
    return {
        # For a price change, what the user currently pays and how it's split —
        # so the review card can show "you pay 320 of this" rather than making
        # them remember the arrangement.
        "current_amount": tracked.amount if tracked else None,
        "current_split_mode": tracked.split_mode if tracked else None,
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
        "cycle": d.cycle.value if hasattr(d.cycle, "value") else d.cycle,
        "amount": d.amount,
        "currency": d.currency,
        "previous_amount": d.previous_amount,
        "cancelled": d.cancelled,
        "confidence": d.confidence,
        "charge_count": d.charge_count,
        "trial_ends_at": d.trial_ends_at.isoformat() if d.trial_ends_at else None,
        "existing_subscription_id": str(d.existing_subscription_id)
            if d.existing_subscription_id else None,
        # A subscription that looks like the same service under another name.
        # Surfaced as a choice, never applied automatically.
        "similar_subscription_id": str(d.similar_subscription_id)
            if d.similar_subscription_id else None,
        "similar_reason": d.similar_reason,
        "similar_name": similar.name if similar else None,
        "similar_amount": similar.amount if similar else None,
        "similar_cycle": (similar.cycle.value if hasattr(similar.cycle, "value") else similar.cycle)
            if similar else None,
        "detected_at": d.detected_at.isoformat() if d.detected_at else None,
    }


def _get_pending(db: Session, user_id: str, detection_id: UUID) -> DetectedSubscription:
    detection = db.query(DetectedSubscription).filter(
        DetectedSubscription.id == detection_id,
        DetectedSubscription.user_id == user_id,
    ).first()
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
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    category: Optional[Category] = None
    amount: Optional[float] = Field(default=None, gt=0)
    cycle: Optional[BillingCycle] = None
    trial_ends_at: Optional[datetime] = None
    # Shared bills: the receipt is the whole cost, but the user may only pay a
    # portion of it (rent split three ways, a household energy bill). Storing
    # the ratio rather than a corrected amount keeps future scans from reading
    # the difference as a price change.
    share_ratio: Optional[float] = Field(default=None, gt=0, le=1)
    # An agreed uneven amount (rent split 320/320/410). Unlike a ratio this is
    # pinned: a later increase to the bill does not silently rescale it.
    share_amount: Optional[float] = Field(default=None, gt=0)
    # The user's answer to "this looks like your existing X": the id to fold
    # this into, or None to add it as a separate subscription.
    replace_subscription_id: Optional[UUID] = None


@router.post("/{detection_id}/approve")
def approve(
    detection_id: UUID,
    overrides: ApproveOverrides,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    detection = _get_pending(db, user_id, detection_id)

    name = overrides.name or detection.merchant
    cycle = overrides.cycle or detection.cycle
    category = overrides.category or detection.category

    # The receipt is the full bill. If the user only pays part of it, `amount`
    # becomes their share and the full cost is kept for future scan comparisons.
    billed = overrides.amount if overrides.amount is not None else detection.amount
    if billed <= 0:
        raise HTTPException(
            status_code=422,
            detail="Enter the recurring price that will be charged after this trial",
        )
    split = resolve_split(billed, overrides.share_ratio, overrides.share_amount)
    trial_supplied = detection.trial_ends_at is not None \
        or "trial_ends_at" in overrides.model_fields_set
    trial_end = overrides.trial_ends_at \
        if "trial_ends_at" in overrides.model_fields_set else detection.trial_ends_at
    trial_end = utc_naive(trial_end) if trial_end else None
    if trial_end and trial_end.date() < utcnow().date():
        raise HTTPException(status_code=422, detail="The trial end date has already passed")

    # Either an automatic price-change match, or the subscription the user chose
    # to replace when told this looks like a service they already track.
    target_id = overrides.replace_subscription_id or detection.existing_subscription_id

    if target_id:
        sub = db.query(Subscription).filter(
            Subscription.id == target_id,
            Subscription.user_id == user_id,
        ).first()
        if not sub:
            raise HTTPException(status_code=404, detail="Tracked subscription no longer exists")

        before = monthly_equivalent(sub.amount, sub.cycle)
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
        sub.currency = detection.currency
        preference = db.query(UserPreference).filter(
            UserPreference.user_id == user_id,
        ).first()
        base = preference.base_currency if preference else "AUD"
        # Do not carry a stale conversion from the former amount/currency.
        # Foreign-currency totals can use the rate service; same-currency
        # amounts are exact immediately.
        sub.converted_amount = sub.amount if sub.currency == base else None
        if trial_supplied:
            sub.trial_ends_at = trial_end
            if trial_end:
                sub.next_due = trial_end
        # Bind the subscription to its source so later scans recognise it even
        # if the analyzer words the merchant differently.
        sub.source_domain = detection.sender_domain
        sub.source_key = detection.product_key or sub.source_key
        if detection.cancelled:
            sub.is_active = False
            db.query(PaymentReminder).filter(
                PaymentReminder.user_id == user_id,
                PaymentReminder.subscription_id == sub.id,
            ).update({PaymentReminder.is_active: False}, synchronize_session=False)
        elif trial_supplied:
            sync_trial_reminder(db, sub)
        elif sub.trial_ends_at and detection.charge_count > 0:
            # A later successful charge is evidence that the trial converted.
            # Clear its automatic cancellation reminder instead of leaving an
            # already-paid trial permanently overdue on the dashboard.
            sub.trial_ends_at = None
            sync_trial_reminder(db, sub)
        after = monthly_equivalent(sub.amount, sub.cycle)
        if after != before:
            log_change(db, sub, ChangeKind.price_change, before, after)
    else:
        preference = db.query(UserPreference).filter(
            UserPreference.user_id == user_id,
        ).first()
        base = preference.base_currency if preference else "AUD"
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
            currency=detection.currency,
            exchange_rate=1.0,
            converted_amount=split.amount if detection.currency == base else None,
            cycle=cycle,
            next_due=trial_end,
            trial_ends_at=trial_end,
            is_active=not detection.cancelled,
        )
        db.add(sub)
        db.flush()
        if trial_end and sub.is_active:
            sync_trial_reminder(db, sub)
        log_change(db, sub, ChangeKind.added, None,
                   monthly_equivalent(split.amount, cycle))

    detection.status = DetectionStatus.approved
    detection.resolved_at = utcnow()
    db.commit()

    logger.info("Detection approved", extra={"user_id": user_id})
    return {"approved": True, "subscription_id": str(sub.id)}


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
