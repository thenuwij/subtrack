import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.middleware.auth import verify_token
from app.models import UserPreference
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/preferences", tags=["preferences"])

class PreferenceUpdate(BaseModel):
    base_currency: str | None = None
    monthly_income: float | None = None

SUPPORTED_CURRENCIES = {"AUD", "USD", "GBP", "SGD", "EUR", "JPY"}

@router.get("")
def get_preferences(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    if not pref:
        # Return default if no preference set yet
        return {"base_currency": "AUD", "monthly_income": None}
    return {"base_currency": pref.base_currency, "monthly_income": pref.monthly_income}

@router.patch("")
def update_preferences(
    body: PreferenceUpdate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    from fastapi import HTTPException

    if body.base_currency is not None and body.base_currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"Unsupported currency: {body.base_currency}")

    if body.monthly_income is not None and body.monthly_income < 0:
        raise HTTPException(status_code=400, detail="monthly_income cannot be negative")

    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    if not pref:
        pref = UserPreference(user_id=user_id)
        db.add(pref)

    # Only overwrite fields the client actually sent
    if body.base_currency is not None:
        pref.base_currency = body.base_currency
    if body.monthly_income is not None:
        pref.monthly_income = body.monthly_income

    db.commit()
    logger.info("Preference updated", extra={"user_id": user_id})
    return {"base_currency": pref.base_currency, "monthly_income": pref.monthly_income}