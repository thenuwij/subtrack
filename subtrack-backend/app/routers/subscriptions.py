from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID
from app.database import get_db
from app.models import Subscription, BillingCycle, Category
from app.middleware.auth import verify_token

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

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

@router.post("/")
def create_subscription(
    data: SubscriptionCreate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    sub = Subscription(**data.model_dump(), user_id=user_id)
    db.add(sub)
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
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(sub, key, value)
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
    db.delete(sub)
    db.commit()
    return {"message": "Deleted successfully"}