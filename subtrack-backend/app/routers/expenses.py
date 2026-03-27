from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID
from app.database import get_db
from app.models import Expense, Category
from app.middleware.auth import verify_token

router = APIRouter(prefix="/expenses", tags=["expenses"])

class ExpenseCreate(BaseModel):
    name: str
    category: Category
    amount: float
    currency: str = "AUD"
    date: datetime
    note: Optional[str] = None

class ExpenseUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[Category] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    date: Optional[datetime] = None
    note: Optional[str] = None

@router.get("/")
def get_expenses(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    return db.query(Expense).filter(
        Expense.user_id == user_id
    ).order_by(Expense.date.desc()).all()

@router.post("/")
def create_expense(
    data: ExpenseCreate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    expense = Expense(**data.model_dump(), user_id=user_id)
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense

@router.patch("/{expense_id}")
def update_expense(
    expense_id: UUID,
    data: ExpenseUpdate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    expense = db.query(Expense).filter(
        Expense.id == expense_id,
        Expense.user_id == user_id
    ).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(expense, key, value)
    db.commit()
    db.refresh(expense)
    return expense

@router.delete("/{expense_id}")
def delete_expense(
    expense_id: UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    expense = db.query(Expense).filter(
        Expense.id == expense_id,
        Expense.user_id == user_id
    ).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    db.delete(expense)
    db.commit()
    return {"message": "Deleted successfully"}