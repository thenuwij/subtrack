from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from app.database import get_db
from app.models import Budget, Category
from app.middleware.auth import verify_token

router = APIRouter(prefix="/budgets", tags=["budgets"])

class BudgetCreate(BaseModel):
    category: Category
    monthly_limit: float
    currency: str = "AUD"

class BudgetUpdate(BaseModel):
    monthly_limit: Optional[float] = None
    currency: Optional[str] = None

@router.get("/")
def get_budgets(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    return db.query(Budget).filter(
        Budget.user_id == user_id
    ).all()

@router.post("/")
def create_budget(
    data: BudgetCreate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    existing = db.query(Budget).filter(
        Budget.user_id == user_id,
        Budget.category == data.category
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Budget for this category already exists")
    budget = Budget(**data.model_dump(), user_id=user_id)
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget

@router.patch("/{budget_id}")
def update_budget(
    budget_id: UUID,
    data: BudgetUpdate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    budget = db.query(Budget).filter(
        Budget.id == budget_id,
        Budget.user_id == user_id
    ).first()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(budget, key, value)
    db.commit()
    db.refresh(budget)
    return budget

@router.delete("/{budget_id}")
def delete_budget(
    budget_id: UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    budget = db.query(Budget).filter(
        Budget.id == budget_id,
        Budget.user_id == user_id
    ).first()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    db.delete(budget)
    db.commit()
    return {"message": "Deleted successfully"}