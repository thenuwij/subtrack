"""Authoritative cadence, normalization, lifecycle, and forecast rules.

Normalized equivalents are budgeting rates. Forecast occurrences are actual
calendar dates. They deliberately use different functions so callers cannot
accidentally describe a quarterly payment as a monthly charge.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from app.models import BillingCycle, PaymentStatus, RecurrenceUnit


DAYS_PER_YEAR = 365
WEEKS_PER_YEAR = 52
MAX_INTERVAL_COUNT = 1200
MAX_FORECAST_OCCURRENCES = 2000


def enum_value(value):
    return value.value if hasattr(value, "value") else value


def utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class Cadence:
    unit: str
    count: int

    def __post_init__(self) -> None:
        unit = str(enum_value(self.unit))
        if unit not in {item.value for item in RecurrenceUnit}:
            raise ValueError("Unsupported recurrence unit")
        if (
            isinstance(self.count, bool)
            or not isinstance(self.count, int)
            or not 1 <= self.count <= MAX_INTERVAL_COUNT
        ):
            raise ValueError(f"Interval count must be between 1 and {MAX_INTERVAL_COUNT}")
        object.__setattr__(self, "unit", unit)


def cadence_from_cycle(cycle) -> Cadence:
    value = enum_value(cycle)
    if value == BillingCycle.weekly.value:
        return Cadence(RecurrenceUnit.week.value, 1)
    if value == BillingCycle.yearly.value:
        return Cadence(RecurrenceUnit.year.value, 1)
    if value == BillingCycle.monthly.value:
        return Cadence(RecurrenceUnit.month.value, 1)
    raise ValueError("A known billing cadence is required")


def cadence_for(item_or_cycle, interval_count: int | None = None) -> Cadence:
    """Resolve a new cadence, falling back to a legacy billing cycle.

    Accepting either a model instance or the legacy cycle keeps migration code,
    tests, and old call sites compatible while making the new fields the single
    source of truth whenever they exist.
    """
    if hasattr(item_or_cycle, "interval_unit"):
        unit = enum_value(getattr(item_or_cycle, "interval_unit", None))
        count = getattr(item_or_cycle, "interval_count", None)
        if unit and count:
            return Cadence(str(unit), int(count))
        return cadence_from_cycle(getattr(item_or_cycle, "cycle", None))
    if interval_count is not None:
        return Cadence(str(enum_value(item_or_cycle)), int(interval_count))
    return cadence_from_cycle(item_or_cycle)


def legacy_cycle_for(unit: str, count: int = 1) -> BillingCycle:
    """Compatibility value for the old non-null PostgreSQL enum column."""
    unit = str(enum_value(unit))
    if unit == RecurrenceUnit.week.value:
        return BillingCycle.weekly
    if unit == RecurrenceUnit.year.value:
        return BillingCycle.yearly
    return BillingCycle.monthly


def annual_equivalent(amount: float, unit_or_item, count: int | None = None) -> float:
    cadence = cadence_for(unit_or_item, count)
    if cadence.unit == RecurrenceUnit.day.value:
        return amount * DAYS_PER_YEAR / cadence.count
    if cadence.unit == RecurrenceUnit.week.value:
        return amount * WEEKS_PER_YEAR / cadence.count
    if cadence.unit == RecurrenceUnit.month.value:
        return amount * 12 / cadence.count
    return amount / cadence.count


def monthly_equivalent(amount: float, unit_or_item, count: int | None = None) -> float:
    return annual_equivalent(amount, unit_or_item, count) / 12


def cadence_label(unit_or_item, count: int | None = None) -> str:
    cadence = cadence_for(unit_or_item, count)
    if cadence.count == 1:
        labels = {"day": "Daily", "week": "Weekly", "month": "Monthly", "year": "Yearly"}
        return labels[cadence.unit]
    if cadence.unit == "week" and cadence.count == 2:
        return "Every 2 weeks"
    plural = cadence.unit if cadence.count == 1 else f"{cadence.unit}s"
    return f"Every {cadence.count} {plural}"


def add_months(anchor: datetime, months: int) -> datetime:
    """Advance from the original anchor without clamp-to-clamp drift.

    January 31 therefore becomes February's last valid day and then March 31,
    and an anchor on the last calendar day of a month remains month-end. This
    preserves the common billing intent for rent, utilities, and subscriptions
    that say "on the last day" while still advancing every later occurrence
    from the original anchor rather than from a previously clamped date.
    """
    index = anchor.year * 12 + anchor.month - 1 + months
    year, month_index = divmod(index, 12)
    month = month_index + 1
    last_day = calendar.monthrange(year, month)[1]
    anchor_is_month_end = anchor.day == calendar.monthrange(anchor.year, anchor.month)[1]
    day = last_day if anchor_is_month_end else min(anchor.day, last_day)
    return anchor.replace(year=year, month=month, day=day)


def occurrence_at(anchor: datetime, cadence: Cadence, period_index: int) -> datetime:
    if period_index < 0:
        raise ValueError("Occurrence index cannot be negative")
    if cadence.unit == RecurrenceUnit.day.value:
        return anchor + timedelta(days=cadence.count * period_index)
    if cadence.unit == RecurrenceUnit.week.value:
        return anchor + timedelta(weeks=cadence.count * period_index)
    month_step = cadence.count * (12 if cadence.unit == RecurrenceUnit.year.value else 1)
    return add_months(anchor, month_step * period_index)


def _first_index_on_or_after(anchor: datetime, cadence: Cadence, start: datetime) -> int:
    if anchor >= start:
        return 0
    if cadence.unit in {RecurrenceUnit.day.value, RecurrenceUnit.week.value}:
        step_days = cadence.count * (7 if cadence.unit == RecurrenceUnit.week.value else 1)
        delta_days = (start.date() - anchor.date()).days
        index = max(0, delta_days // step_days)
        if occurrence_at(anchor, cadence, index).date() < start.date():
            index += 1
        return index

    step_months = cadence.count * (12 if cadence.unit == RecurrenceUnit.year.value else 1)
    elapsed_months = (start.year - anchor.year) * 12 + start.month - anchor.month
    index = max(0, elapsed_months // step_months)
    while occurrence_at(anchor, cadence, index).date() < start.date():
        index += 1
    return index


def project_next_occurrence(
    next_due: datetime | None,
    unit_or_item,
    now: datetime,
    interval_count: int | None = None,
    recurrence_end_at: datetime | None = None,
) -> tuple[datetime | None, str]:
    if not next_due:
        return None, "missing"
    anchor = utc_naive(next_due)
    now = utc_naive(now)
    cadence = cadence_for(unit_or_item, interval_count)
    index = _first_index_on_or_after(anchor, cadence, now)
    due = occurrence_at(anchor, cadence, index)
    end = utc_naive(recurrence_end_at) if recurrence_end_at else None
    if end and due > end:
        return None, "ended"
    # Keep the old source identifier stable for existing frontend releases.
    return due, "recorded" if index == 0 else "projected_from_recorded_cycle"


def occurrences_between(
    next_due: datetime | None,
    unit_or_item,
    start: datetime,
    end: datetime,
    *,
    interval_count: int | None = None,
    recurrence_end_at: datetime | None = None,
    limit: int = MAX_FORECAST_OCCURRENCES,
) -> list[datetime]:
    if not next_due:
        return []
    start, end = utc_naive(start), utc_naive(end)
    if end < start:
        raise ValueError("Forecast end must not be before its start")
    anchor = utc_naive(next_due)
    cadence = cadence_for(unit_or_item, interval_count)
    index = _first_index_on_or_after(anchor, cadence, start)
    recurrence_end = utc_naive(recurrence_end_at) if recurrence_end_at else None
    rows: list[datetime] = []
    while len(rows) < limit:
        due = occurrence_at(anchor, cadence, index)
        if due > end or (recurrence_end and due > recurrence_end):
            break
        rows.append(due)
        index += 1
    if len(rows) == limit:
        next_occurrence = occurrence_at(anchor, cadence, index)
        if next_occurrence <= end and not (
            recurrence_end and next_occurrence > recurrence_end
        ):
            raise ValueError("Forecast contains too many occurrences")
    return rows


def effective_status(subscription, now: datetime | None = None) -> str:
    now = utc_naive(now or datetime.now(timezone.utc))
    status = str(enum_value(getattr(subscription, "status", None) or "active"))
    if not getattr(subscription, "is_active", True) and status == PaymentStatus.active.value:
        status = PaymentStatus.cancelled.value
    end = getattr(subscription, "recurrence_end_at", None)
    if end and utc_naive(end).date() < now.date():
        return PaymentStatus.ended.value
    cancellation = getattr(subscription, "cancellation_effective_at", None)
    if status == PaymentStatus.cancelling.value and cancellation:
        if utc_naive(cancellation).date() <= now.date():
            return PaymentStatus.cancelled.value
    paused_until = getattr(subscription, "paused_until", None)
    if status == PaymentStatus.paused.value and paused_until:
        if utc_naive(paused_until).date() <= now.date():
            return PaymentStatus.active.value
    return status


def contributes_to_current_total(subscription, now: datetime | None = None) -> bool:
    status = effective_status(subscription, now)
    return status in {PaymentStatus.active.value, PaymentStatus.cancelling.value}


def forecast_end_for(subscription) -> datetime | None:
    cancellation = getattr(subscription, "cancellation_effective_at", None)
    if cancellation and effective_status(subscription) == PaymentStatus.cancelling.value:
        # Cancellation-at-period-end is exclusive: the service stops at this
        # instant, so a projected renewal at the same instant is not owed.
        cancellation = utc_naive(cancellation) - timedelta(microseconds=1)
    values: Iterable[datetime | None] = (
        getattr(subscription, "recurrence_end_at", None),
        cancellation,
    )
    present = [utc_naive(value) for value in values if value]
    return min(present) if present else None
