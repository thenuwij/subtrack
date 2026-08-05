import logging
import math
from datetime import date, datetime, timedelta, timezone
from threading import RLock
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import verify_token
from app.models import ExchangeRateSnapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rates", tags=["rates"])

SUPPORTED_CURRENCIES = frozenset({"AUD", "USD", "GBP", "SGD", "EUR", "JPY"})
FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
RATE_PROVIDER = "frankfurter"
_CACHE_TTL = timedelta(hours=1)

# The process-local cache remains the zero-query fast path. The database cache
# underneath it is shared by all Render workers and survives restarts.
_cache: dict[str, dict[str, Any]] = {}
_cache_lock = RLock()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _normalise_base(base: str) -> str:
    if not isinstance(base, str):
        raise TypeError("Unsupported currency")
    normalised = base.upper()
    if len(normalised) != 3 or normalised not in SUPPORTED_CURRENCIES:
        raise ValueError(f"Unsupported currency: {base}")
    return normalised


def _validate_rates(raw_rates: object, base: str) -> dict[str, float]:
    """Return a complete, bounded provider map or reject the snapshot.

    Requiring every supported target prevents a missing or malformed rate from
    turning into an accidental 1:1 conversion in less defensive clients.
    Unknown provider currencies are discarded before persistence.
    """
    if not isinstance(raw_rates, dict):
        raise TypeError("Exchange-rate response did not contain a rates object")
    expected = SUPPORTED_CURRENCIES - {base}
    validated: dict[str, float] = {}
    for currency in sorted(expected):
        value = raw_rates.get(currency)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"Exchange-rate response omitted a valid {currency} rate")
        numeric = float(value)
        if not math.isfinite(numeric) or numeric <= 0:
            raise ValueError(
                f"Exchange-rate response contained an invalid {currency} rate"
            )
        validated[currency] = numeric
    return validated


def _normalise_provider_date(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed.isoformat()


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


def conversion_for_storage(
    amount: float,
    currency: str,
    base: str,
    db: Session,
) -> tuple[float | None, float | None, str]:
    """Derive an entry conversion from Subtrack's shared server snapshot.

    Browser-supplied converted values are display hints, not trustworthy
    financial data. New and edited records use this helper so direct API calls,
    Gmail approval, and assistant actions all store the same conversion. A
    missing/unsupported rate remains explicitly unconverted instead of being
    represented as 1:1.
    """
    base = _normalise_base(base)
    currency = currency.upper()
    if currency == base:
        return round(amount, 2), 1.0, "exact_base_currency"
    if currency not in SUPPORTED_CURRENCIES:
        return None, None, "unsupported_currency"
    snapshot = get_cached_rate_snapshot(base, db)
    rate = snapshot.get("rates", {}).get(currency) if snapshot else None
    if not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate <= 0:
        return None, None, "unconverted"
    inverse = 1 / float(rate)
    quality = "stale_rate" if snapshot.get("stale") else "current_rate"
    return round(amount * inverse, 2), round(inverse, 8), quality


def _memory_entry(base: str) -> dict[str, Any] | None:
    with _cache_lock:
        entry = _cache.get(base)
        if entry is None:
            return None
        return {**entry, "rates": dict(entry["rates"])}


def _store_memory_entry(base: str, entry: dict[str, Any]) -> None:
    with _cache_lock:
        _cache[base] = {**entry, "rates": dict(entry["rates"])}


def _entry_is_fresh(entry: dict[str, Any], *, now: datetime | None = None) -> bool:
    current = now or _utcnow()
    age = current - _utc_naive(entry["fetched_at"])
    return timedelta(0) <= age < _CACHE_TTL


def is_cache_valid(base: str) -> bool:
    """Return whether the in-process snapshot is less than one hour old."""
    try:
        base = _normalise_base(base)
    except (TypeError, ValueError):
        return False
    entry = _memory_entry(base)
    return bool(entry and _entry_is_fresh(entry))


def _snapshot_payload(base: str, entry: dict[str, Any]) -> dict[str, Any]:
    fetched_at = _utc_naive(entry["fetched_at"])
    return {
        "base": base,
        "rates": dict(entry["rates"]),
        "cached": True,
        "stale": not _entry_is_fresh(entry),
        "fetched_at": fetched_at.isoformat(),
        "provider": entry.get("provider", RATE_PROVIDER),
        "provider_date": entry.get("provider_date"),
        "cache_source": entry.get("cache_source", "memory"),
    }


def _load_persisted_entry(db: Session, base: str) -> dict[str, Any] | None:
    try:
        row = db.get(ExchangeRateSnapshot, base)
    except SQLAlchemyError as exc:
        logger.warning(
            "Could not read the shared exchange-rate cache",
            extra={"base": base, "error": str(exc)},
        )
        # Both current call sites use a read-only session at this point. Clear
        # PostgreSQL's failed-transaction state so a rolling deploy with the
        # table not created yet does not break the finance query that follows.
        try:
            db.rollback()
        except SQLAlchemyError:
            logger.exception("Could not reset session after FX cache read failure")
        return None
    if row is None:
        return None
    try:
        rates = _validate_rates(row.rates, base)
    except (TypeError, ValueError) as exc:
        logger.error(
            "Ignoring an invalid persisted exchange-rate snapshot",
            extra={"base": base, "error": str(exc)},
        )
        return None
    if not isinstance(row.fetched_at, datetime):
        logger.error(
            "Ignoring exchange-rate snapshot without fetched_at", extra={"base": base}
        )
        return None
    return {
        "rates": rates,
        "fetched_at": _utc_naive(row.fetched_at),
        "provider": row.provider or RATE_PROVIDER,
        "provider_date": _normalise_provider_date(row.provider_date),
        "cache_source": "persistent_cache",
    }


def get_cached_rate_snapshot(base: str, db: Session | None = None) -> dict | None:
    """Return the newest usable in-process or persisted snapshot.

    This never performs external provider I/O. A supplied database session may
    hydrate the process cache after a restart. Stale data stays available but
    is always labelled so finance answers describe it as an estimate.
    """
    try:
        base = _normalise_base(base)
    except (TypeError, ValueError):
        return None

    memory = _memory_entry(base)
    if memory is not None and _entry_is_fresh(memory):
        return _snapshot_payload(base, memory)

    persisted = _load_persisted_entry(db, base) if db is not None else None
    chosen = memory
    if persisted is not None and (
        chosen is None or persisted["fetched_at"] > chosen["fetched_at"]
    ):
        chosen = persisted
        _store_memory_entry(base, chosen)
    if chosen is None:
        return None
    return _snapshot_payload(base, chosen)


def _persist_snapshot(
    db: Session,
    *,
    base: str,
    rates: dict[str, float],
    fetched_at: datetime,
    provider_date: str | None,
) -> None:
    values = {
        "base_currency": base,
        "rates": rates,
        "provider": RATE_PROVIDER,
        "provider_date": provider_date,
        "fetched_at": fetched_at,
        "updated_at": fetched_at,
    }
    update_values = {
        key: value for key, value in values.items() if key != "base_currency"
    }
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(ExchangeRateSnapshot).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[ExchangeRateSnapshot.base_currency],
            set_=update_values,
        )
        db.execute(statement)
    elif dialect == "sqlite":
        statement = sqlite_insert(ExchangeRateSnapshot).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[ExchangeRateSnapshot.base_currency],
            set_=update_values,
        )
        db.execute(statement)
    else:
        row = db.get(ExchangeRateSnapshot, base)
        if row is None:
            db.add(ExchangeRateSnapshot(**values))
        else:
            for key, value in update_values.items():
                setattr(row, key, value)
    db.commit()


async def _fetch_provider_snapshot(base: str) -> tuple[dict[str, float], str | None]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(FRANKFURTER_URL, params={"from": base})
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        raise TypeError("Exchange-rate provider returned an invalid response")
    return _validate_rates(data.get("rates"), base), _normalise_provider_date(
        data.get("date")
    )


@router.get("")
async def get_rates(
    base: str = "AUD",
    _user: str = Depends(verify_token),
    db: Session = Depends(get_db),  # noqa: B008
):
    try:
        base = _normalise_base(base)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    snapshot = get_cached_rate_snapshot(base, db)
    if snapshot is not None and not snapshot["stale"]:
        logger.info("Returning cached rates", extra={"base": base})
        return snapshot

    # Provider I/O should not reserve a pooled database connection. Any stale
    # snapshot is already copied into a plain dict and can be returned safely.
    db.commit()
    logger.info("Fetching live rates", extra={"base": base})
    try:
        provider_rates, provider_date = await _fetch_provider_snapshot(base)
    except Exception as exc:  # noqa: BLE001 - provider failures use a truthful stale fallback
        logger.warning(
            "Exchange-rate provider unavailable",
            extra={"error": str(exc), "base": base},
        )
        if snapshot is not None:
            logger.warning("Returning stale exchange rates", extra={"base": base})
            return {
                **snapshot,
                "stale": True,
                "fallback_reason": "provider_unavailable",
            }
        raise HTTPException(
            status_code=503,
            detail="Exchange rate service unavailable and no cached rates exist.",
        ) from None

    fetched_at = _utcnow()
    try:
        _persist_snapshot(
            db,
            base=base,
            rates=provider_rates,
            fetched_at=fetched_at,
            provider_date=provider_date,
        )
    except SQLAlchemyError as exc:
        try:
            db.rollback()
        except SQLAlchemyError:
            logger.exception("Could not reset session after FX cache write failure")
        # The live answer remains useful, while the exception is visible to
        # operations and the in-process fast cache still prevents a hot loop.
        logger.exception(
            "Could not persist exchange-rate snapshot",
            extra={"base": base, "error": str(exc)},
        )

    entry = {
        "rates": provider_rates,
        "fetched_at": fetched_at,
        "provider": RATE_PROVIDER,
        "provider_date": provider_date,
        "cache_source": "provider",
    }
    _store_memory_entry(base, entry)
    logger.info(
        "Exchange rates fetched and cached",
        extra={"base": base, "currencies": sorted(provider_rates)},
    )
    return {
        "base": base,
        "rates": dict(provider_rates),
        "cached": False,
        "stale": False,
        "fetched_at": fetched_at.isoformat(),
        "provider": RATE_PROVIDER,
        "provider_date": provider_date,
        "cache_source": "provider",
    }
