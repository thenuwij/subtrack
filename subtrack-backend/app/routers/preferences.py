import logging
import math
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import verify_token
from app.models import UserPreference
from app.routers.rates import get_cached_rate_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/preferences", tags=["preferences"])

class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    base_currency: Literal["AUD", "USD", "GBP", "SGD", "EUR", "JPY"] | None = None
    monthly_income: float | None = Field(default=None, ge=0)

@router.get("")
def get_preferences(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    if not pref:
        # Return default if no preference set yet
        return {"base_currency": "AUD", "monthly_income": None, "timezone": "UTC"}
    return {
        "base_currency": pref.base_currency,
        "monthly_income": pref.monthly_income,
        "timezone": pref.timezone or "UTC",
    }

@router.patch("")
def update_preferences(
    body: PreferenceUpdate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db)
):
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    if not pref:
        pref = UserPreference(user_id=user_id)
        db.add(pref)

    # Monthly income is denominated in the selected base currency. Changing
    # only the currency label would silently turn A$5,000 into US$5,000, so an
    # existing value is converted atomically from a fresh trusted snapshot.
    old_base = pref.base_currency or "AUD"
    new_base = body.base_currency or old_base
    income_converted = False
    income_rate_as_of = None
    if (
        new_base != old_base
        and pref.monthly_income is not None
        and "monthly_income" not in body.model_fields_set
    ):
        snapshot = get_cached_rate_snapshot(old_base, db=db)
        rate = snapshot.get("rates", {}).get(new_base) if snapshot else None
        if (
            not snapshot
            or snapshot.get("stale")
            or not isinstance(rate, (int, float))
            or not math.isfinite(rate)
            or rate <= 0
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Your saved income is in the current base currency and a fresh "
                    "conversion is unavailable. Retry after rates refresh, or clear "
                    "the income value before changing currency."
                ),
            )
        pref.monthly_income = round(pref.monthly_income * float(rate), 2)
        income_converted = True
        income_rate_as_of = snapshot.get("fetched_at")

    # Only overwrite fields the client actually sent.
    if body.base_currency is not None:
        pref.base_currency = new_base
    if "monthly_income" in body.model_fields_set:
        pref.monthly_income = body.monthly_income

    db.commit()
    logger.info("Preference updated", extra={"user_id": user_id})
    return {
        "base_currency": pref.base_currency,
        "monthly_income": pref.monthly_income,
        "timezone": pref.timezone or "UTC",
        "income_converted": income_converted,
        "income_conversion_rate_as_of": income_rate_as_of,
    }
