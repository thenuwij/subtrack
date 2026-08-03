from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import NamedTuple, Optional
from datetime import datetime
from uuid import UUID
from app.database import get_db
from app.models import Subscription, BillingCycle, Category, SubscriptionChange, ChangeKind
from app.middleware.auth import verify_token

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

# Weekly/yearly costs have to be normalised before they can be compared month to month.
# 52 weeks / 12 months — not 4.33, which only covers 51.96 weeks a year and
# leaves the annual figure short on a large weekly bill.
WEEKS_PER_MONTH = 52 / 12

CYCLE_TO_MONTHLY = {
    BillingCycle.weekly: lambda a: a * WEEKS_PER_MONTH,
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
    name: str
    category: Category
    amount: float
    currency: str = "AUD"
    exchange_rate: float = 1.0
    converted_amount: Optional[float] = None
    cycle: BillingCycle
    next_due: Optional[datetime] = None
    # Shared bills: send the full cost and the caller's portion (e.g. 1/3).
    # `amount` is then derived and represents only what this user pays.
    full_amount: Optional[float] = None
    share_ratio: Optional[float] = Field(default=None, gt=0, le=1)
    share_amount: Optional[float] = Field(default=None, gt=0)

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
    full_amount: Optional[float] = None
    share_ratio: Optional[float] = Field(default=None, gt=0, le=1)
    share_amount: Optional[float] = Field(default=None, gt=0)

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
    fields = data.model_dump()
    # The caller sends the whole bill plus how it's split; `amount` ends up as
    # this user's portion so every downstream total needs no special case.
    billed = fields.pop("full_amount") or fields["amount"]
    split = resolve_split(billed, fields.pop("share_ratio"), fields.pop("share_amount"))
    fields["amount"] = split.amount
    if fields.get("converted_amount") is None:
        fields["converted_amount"] = split.amount

    sub = Subscription(**fields, user_id=user_id,
                       full_amount=split.full_amount,
                       share_ratio=split.share_ratio,
                       split_mode=split.split_mode)
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

    fields = data.model_dump(exclude_none=True)
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