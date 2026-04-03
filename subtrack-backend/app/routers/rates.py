import logging
import httpx
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from app.middleware.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rates", tags=["rates"])

SUPPORTED_CURRENCIES = {"AUD", "USD", "GBP", "SGD", "EUR", "JPY"}
FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"

# In-memory cache — stores rates per base currency
# Structure: { "AUD": { "rates": {...}, "fetched_at": datetime } }
_cache: dict = {}

# ── Pure functions (no side effects, easy to test) ────────────────────────

def convert_amount(amount: float, rate: float) -> float:
    """Multiply amount by exchange rate. Raises if either is invalid."""
    if amount < 0:
        raise ValueError("Amount cannot be negative")
    if rate <= 0:
        raise ValueError("Rate must be positive")
    return round(amount * rate, 2)

def recalculate_rate(original: float, converted: float) -> float:
    """Derive the implied rate from a manual override."""
    if original <= 0:
        raise ValueError("Original amount must be positive")
    if converted < 0:
        raise ValueError("Converted amount cannot be negative")
    return round(converted / original, 6)

def is_cache_valid(base: str) -> bool:
    """Returns True if cached rates exist and are less than 1 hour old."""
    if base not in _cache:
        return False
    age = datetime.utcnow() - _cache[base]["fetched_at"]
    return age < timedelta(hours=1)

# ── Route ─────────────────────────────────────────────────────────────────

@router.get("")
async def get_rates(base: str = "AUD", user=Depends(verify_token)):
    if base not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"Unsupported currency: {base}")

    # Return cache if still valid
    if is_cache_valid(base):
        logger.info("Returning cached rates", extra={"base": base})
        return {
            "base": base,
            "rates": _cache[base]["rates"],
            "cached": True,
            "fetched_at": _cache[base]["fetched_at"].isoformat(),
        }

    # Fetch from Frankfurter
    logger.info("Fetching live rates", extra={"base": base})
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(FRANKFURTER_URL, params={"from": base})
            response.raise_for_status()
            data = response.json()

        # Filter to only our supported currencies
        rates = {k: v for k, v in data["rates"].items() if k in SUPPORTED_CURRENCIES}

        # Store in cache
        _cache[base] = {"rates": rates, "fetched_at": datetime.utcnow()}
        logger.info("Rates fetched and cached", extra={"base": base, "currencies": list(rates.keys())})

        return {"base": base, "rates": rates, "cached": False, "fetched_at": _cache[base]["fetched_at"].isoformat()}

    except Exception as e:
        logger.error("Frankfurter unavailable", extra={"error": str(e), "base": base})

        # Fallback to stale cache if it exists
        if base in _cache:
            logger.warning("Returning stale cache as fallback", extra={"base": base})
            return {**_cache[base], "cached": True, "stale": True, "fetched_at": _cache[base]["fetched_at"].isoformat()}

        # No cache at all — hard failure
        raise HTTPException(status_code=503, detail="Exchange rate service unavailable and no cached rates exist.")