from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID
from app.database import get_db
from app.models import SavingsGoal
from app.middleware.auth import verify_token

router = APIRouter(prefix="/savings", tags=["savings"])

class SavingsGoalCreate(BaseModel):
    name: str
    target_amount: float
    current_amount: float = 0.0
    currency: str = "AUD"
    target_date: Optional[datetime] = None

class SavingsGoalUpdate(BaseModel):
    name: Optional[str] = None
    target_amount: Optional[float] = None
    current_amount: Optional[float] = None
    currency: Optional[str] = None
    target_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None

@router.get("/")
def get_savings(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    return db.query(SavingsGoal).filter(
        SavingsGoal.user_id == user_id
    ).order_by(SavingsGoal.created_at.desc()).all()

@router.post("/")
def create_savings_goal(
    data: SavingsGoalCreate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    goal = SavingsGoal(**data.model_dump(), user_id=user_id, created_by="user")
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal

@router.patch("/{goal_id}")
def update_savings_goal(
    goal_id: UUID,
    data: SavingsGoalUpdate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    goal = db.query(SavingsGoal).filter(
        SavingsGoal.id == goal_id,
        SavingsGoal.user_id == user_id
    ).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Savings goal not found")
    for key, value in data.model_dump(exclude_none=True).items():
        setattr(goal, key, value)
    db.commit()
    db.refresh(goal)
    return goal

@router.delete("/{goal_id}")
def delete_savings_goal(
    goal_id: UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    goal = db.query(SavingsGoal).filter(
        SavingsGoal.id == goal_id,
        SavingsGoal.user_id == user_id
    ).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Savings goal not found")
    db.delete(goal)
    db.commit()
    return {"message": "Deleted successfully"}
