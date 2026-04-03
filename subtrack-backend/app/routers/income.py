from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID
from app.database import get_db
from app.models import Income, Frequency
from app.middleware.auth import verify_token

router = APIRouter(prefix="/income", tags=["income"])

class IncomeCreate(BaseModel):
    amount: float
    currency: str = "AUD"
    exchange_rate: float = 1.0
    converted_amount: Optional[float] = None
    frequency: Frequency
    source: Optional[str] = None
    date: datetime
    note: Optional[str] = None

class IncomeUpdate(BaseModel):
    amount: Optional[float] = None
    currency: Optional[str] = None
    exchange_rate: Optional[float] = None
    converted_amount: Optional[float] = None
    frequency: Optional[Frequency] = None
    source: Optional[str] = None
    date: Optional[datetime] = None
    note: Optional[str] = None

@router.get("/")
def get_income(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    return db.query(Income).filter(
        Income.user_id == user_id
    ).order_by(Income.date.desc()).all()

@router.post("/")
def create_income(
    data: IncomeCreate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    entry = Income(**data.model_dump(), user_id=user_id)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry

@router.patch("/{income_id}")
def update_income(
    income_id: UUID,
    data: IncomeUpdate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    entry = db.query(Income).filter(
        Income.id == income_id,
        Income.user_id == user_id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Income not found")
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(entry, key, value)
    db.commit()
    db.refresh(entry)
    return entry

@router.delete("/{income_id}")
def delete_income(
    income_id: UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    entry = db.query(Income).filter(
        Income.id == income_id,
        Income.user_id == user_id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Income not found")
    db.delete(entry)
    db.commit()
    return {"message": "Deleted successfully"}
