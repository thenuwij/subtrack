"""Backward-compatible imports for calendar-safe recurrence rules."""
from app.services.recurrence import (  # noqa: F401
    add_months,
    occurrences_between,
    project_next_occurrence,
    utc_naive,
)
