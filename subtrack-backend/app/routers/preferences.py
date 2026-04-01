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
    base_currency: str

SUPPORTED_CURRENCIES = {"AUD", "USD", "GBP", "SGD", "EUR", "JPY"}

@router.get("")
def get_preferences(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    if not pref:
        # Return default if no preference set yet
        return {"base_currency": "AUD"}
    return {"base_currency": pref.base_currency}

@router.patch("")
def update_preferences(
    body: PreferenceUpdate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    if body.base_currency not in SUPPORTED_CURRENCIES:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unsupported currency: {body.base_currency}")

    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    if pref:
        pref.base_currency = body.base_currency
    else:
        pref = UserPreference(user_id=user_id, base_currency=body.base_currency)
        db.add(pref)

    db.commit()
    logger.info("Preference updated", extra={"user_id": user_id, "base_currency": body.base_currency})
    return {"base_currency": pref.base_currency}