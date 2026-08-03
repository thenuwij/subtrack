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
from pydantic import BaseModel, Field
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
)
from app.routers.subscriptions import (log_change, monthly_equivalent, rebill,
                                       resolve_split)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/detected", tags=["detected"])


def _serialize(d: DetectedSubscription, tracked: Optional[Subscription] = None) -> dict:
    return {
        # For a price change, what the user currently pays and how it's split —
        # so the review card can show "you pay 320 of this" rather than making
        # them remember the arrangement.
        "current_amount": tracked.amount if tracked else None,
        "current_split_mode": tracked.split_mode if tracked else None,
        "id": str(d.id),
        "merchant": d.merchant,
        "sender_domain": d.sender_domain,
        "category": d.category.value if hasattr(d.category, "value") else d.category,
        "cycle": d.cycle.value if hasattr(d.cycle, "value") else d.cycle,
        "amount": d.amount,
        "currency": d.currency,
        "previous_amount": d.previous_amount,
        "cancelled": d.cancelled,
        "confidence": d.confidence,
        "charge_count": d.charge_count,
        "existing_subscription_id": str(d.existing_subscription_id)
            if d.existing_subscription_id else None,
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

    tracked_ids = {d.existing_subscription_id for d in pending if d.existing_subscription_id}
    tracked = {
        s.id: s for s in db.query(Subscription).filter(Subscription.id.in_(tracked_ids)).all()
    } if tracked_ids else {}

    return [_serialize(d, tracked.get(d.existing_subscription_id)) for d in pending]


class ApproveOverrides(BaseModel):
    """The user can correct the detection before it becomes real."""
    name: Optional[str] = None
    category: Optional[Category] = None
    amount: Optional[float] = None
    cycle: Optional[BillingCycle] = None
    # Shared bills: the receipt is the whole cost, but the user may only pay a
    # portion of it (rent split three ways, a household energy bill). Storing
    # the ratio rather than a corrected amount keeps future scans from reading
    # the difference as a price change.
    share_ratio: Optional[float] = Field(default=None, gt=0, le=1)
    # An agreed uneven amount (rent split 320/320/410). Unlike a ratio this is
    # pinned: a later increase to the bill does not silently rescale it.
    share_amount: Optional[float] = Field(default=None, gt=0)


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
    split = resolve_split(billed, overrides.share_ratio, overrides.share_amount)

    if detection.existing_subscription_id:
        # A price change to something already tracked: update, don't duplicate.
        sub = db.query(Subscription).filter(
            Subscription.id == detection.existing_subscription_id,
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
        sub.cycle = cycle
        sub.currency = detection.currency
        after = monthly_equivalent(sub.amount, sub.cycle)
        if after != before:
            log_change(db, sub, ChangeKind.price_change, before, after)
    else:
        sub = Subscription(
            user_id=user_id,
            name=name,
            category=category,
            amount=split.amount,
            full_amount=split.full_amount,
            share_ratio=split.share_ratio,
            split_mode=split.split_mode,
            currency=detection.currency,
            exchange_rate=1.0,
            converted_amount=split.amount,
            cycle=cycle,
            is_active=not detection.cancelled,
        )
        db.add(sub)
        db.flush()
        log_change(db, sub, ChangeKind.added, None,
                   monthly_equivalent(split.amount, cycle))

    detection.status = DetectionStatus.approved
    detection.resolved_at = datetime.utcnow()
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
