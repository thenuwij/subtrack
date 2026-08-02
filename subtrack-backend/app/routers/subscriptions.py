from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID
from app.database import get_db
from app.models import Subscription, BillingCycle, Category, SubscriptionChange, ChangeKind
from app.middleware.auth import verify_token

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

# Weekly/yearly costs have to be normalised before they can be compared month to month.
CYCLE_TO_MONTHLY = {
    BillingCycle.weekly: lambda a: a * 4.33,
    BillingCycle.yearly: lambda a: a / 12,
    BillingCycle.monthly: lambda a: a,
}

def monthly_equivalent(amount: float, cycle) -> float:
    return CYCLE_TO_MONTHLY.get(cycle, lambda a: a)(amount)

def log_change(db: Session, sub: Subscription, kind: ChangeKind,
               old_monthly: float | None, new_monthly: float | None):
    db.add(SubscriptionChange(
        user_id=sub.user_id,
        subscription_id=sub.id,
        name=sub.name,
        kind=kind,
        old_monthly=old_monthly,
        new_monthly=new_monthly,
        currency=sub.currency,
    ))

class SubscriptionCreate(BaseModel):
    name: str
    category: Category
    amount: float
    currency: str = "AUD"
    exchange_rate: float = 1.0
    converted_amount: Optional[float] = None 
    cycle: BillingCycle
    next_due: Optional[datetime] = None

class SubscriptionUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[Category] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    exchange_rate: Optional[float] = None
    converted_amount: Optional[float] = None
    cycle: Optional[BillingCycle] = None
    next_due: Optional[datetime] = None
    is_active: Optional[bool] = None
    
@router.get("/")
def get_subscriptions(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    return db.query(Subscription).filter(
        Subscription.user_id == user_id,
        Subscription.is_active == True
    ).all()

@router.get("/changes")
def get_changes(
    days: int = 30,
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
    sub = Subscription(**data.model_dump(), user_id=user_id)
    db.add(sub)
    db.flush()   # need sub.id before logging the change
    log_change(db, sub, ChangeKind.added, None, monthly_equivalent(sub.amount, sub.cycle))
    db.commit()
    db.refresh(sub)
    return sub

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
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    before = monthly_equivalent(sub.amount, sub.cycle)

    for key, value in data.model_dump(exclude_none=True).items():
        setattr(sub, key, value)

    after = monthly_equivalent(sub.amount, sub.cycle)
    if after != before:
        log_change(db, sub, ChangeKind.price_change, before, after)

    db.commit()
    db.refresh(sub)
    return sub

@router.delete("/{sub_id}")
def delete_subscription(
    sub_id: UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    sub = db.query(Subscription).filter(
        Subscription.id == sub_id,
        Subscription.user_id == user_id
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    log_change(db, sub, ChangeKind.removed, monthly_equivalent(sub.amount, sub.cycle), None)
    db.delete(sub)
    db.commit()
    return {"message": "Deleted successfully"}