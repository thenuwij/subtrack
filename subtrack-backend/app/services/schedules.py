"""Calendar-safe projection of recurring billing dates."""
import calendar
from datetime import datetime, timedelta, timezone


def utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def add_months(value: datetime, months: int) -> datetime:
    index = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(index, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def project_next_occurrence(
    next_due: datetime | None,
    cycle,
    now: datetime,
) -> tuple[datetime | None, str]:
    """Project a stale recorded due date without mutating the subscription.

    Billing dates are day-level promises. A charge recorded for today remains
    today's occurrence even after midnight rather than jumping a whole cycle.
    """
    if not next_due:
        return None, "missing"
    due = utc_naive(next_due)
    now = utc_naive(now)
    if due.date() >= now.date():
        return due, "recorded"

    original = due
    cycle_value = cycle.value if hasattr(cycle, "value") else cycle
    if cycle_value == "weekly":
        days_behind = (now.date() - due.date()).days
        weeks = max(1, days_behind // 7 + (1 if days_behind % 7 else 0))
        due += timedelta(days=weeks * 7)
    else:
        elapsed_months = (now.year - due.year) * 12 + now.month - due.month
        step = 12 if cycle_value == "yearly" else 1
        periods = max(1, elapsed_months // step)
        due = add_months(original, periods * step)
        if due.date() < now.date():
            due = add_months(original, (periods + 1) * step)
    return due, "projected_from_recorded_cycle"
