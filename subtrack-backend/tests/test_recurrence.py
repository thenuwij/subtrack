import os
import unittest
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

from app.models import BillingCycle, PaymentStatus  # noqa: E402
from app.services.recurrence import (  # noqa: E402
    Cadence,
    annual_equivalent,
    effective_status,
    monthly_equivalent,
    occurrence_at,
    occurrences_between,
    project_next_occurrence,
)


class RecurrenceCalculationTests(unittest.TestCase):
    def test_supported_presets_and_custom_intervals_normalise_correctly(self):
        cases = [
            (120, "month", 3, 40, 480),       # quarterly
            (120, "month", 6, 20, 240),       # semiannual
            (120, "month", 2, 60, 720),
            (10, "week", 2, 260 / 12, 260),   # fortnightly
            (10, "week", 4, 130 / 12, 130),   # every four weeks
            (10, "day", 10, 365 / 12, 365),
            (240, "year", 2, 10, 120),
        ]
        for amount, unit, count, monthly, yearly in cases:
            with self.subTest(unit=unit, count=count):
                self.assertAlmostEqual(
                    monthly_equivalent(amount, unit, count), monthly, places=8,
                )
                self.assertAlmostEqual(
                    annual_equivalent(amount, unit, count), yearly, places=8,
                )

    def test_every_four_weeks_is_not_a_calendar_month(self):
        four_week_annual = annual_equivalent(100, "week", 4)
        monthly_annual = annual_equivalent(100, "month", 1)
        self.assertEqual(four_week_annual, 1300)
        self.assertEqual(monthly_annual, 1200)

    def test_legacy_cycles_remain_compatible_during_rolling_deploy(self):
        self.assertEqual(monthly_equivalent(10, BillingCycle.weekly), 520 / 12)
        self.assertEqual(monthly_equivalent(10, BillingCycle.monthly), 10)
        self.assertEqual(monthly_equivalent(120, BillingCycle.yearly), 10)

    def test_month_end_progression_uses_the_original_anchor(self):
        anchor = datetime(2025, 1, 31, 9, 30)
        cadence = Cadence("month", 1)
        self.assertEqual(occurrence_at(anchor, cadence, 1), datetime(2025, 2, 28, 9, 30))
        self.assertEqual(occurrence_at(anchor, cadence, 2), datetime(2025, 3, 31, 9, 30))
        self.assertEqual(occurrence_at(anchor, cadence, 3), datetime(2025, 4, 30, 9, 30))

    def test_month_end_intent_is_preserved_from_a_short_month_anchor(self):
        anchor = datetime(2026, 6, 30, 9, 30)
        cadence = Cadence("month", 1)
        self.assertEqual(occurrence_at(anchor, cadence, 1), datetime(2026, 7, 31, 9, 30))
        self.assertEqual(occurrence_at(anchor, cadence, 2), datetime(2026, 8, 31, 9, 30))

    def test_non_month_end_day_does_not_drift_after_february_clamp(self):
        anchor = datetime(2025, 1, 30, 9, 30)
        cadence = Cadence("month", 1)
        self.assertEqual(occurrence_at(anchor, cadence, 1), datetime(2025, 2, 28, 9, 30))
        self.assertEqual(occurrence_at(anchor, cadence, 2), datetime(2025, 3, 30, 9, 30))

    def test_leap_day_yearly_progression_recovers_in_the_next_leap_year(self):
        anchor = datetime(2024, 2, 29, 8, 0)
        cadence = Cadence("year", 1)
        self.assertEqual(occurrence_at(anchor, cadence, 1), datetime(2025, 2, 28, 8, 0))
        self.assertEqual(occurrence_at(anchor, cadence, 4), datetime(2028, 2, 29, 8, 0))

    def test_stale_date_projects_without_mutating_the_anchor(self):
        anchor = datetime(2026, 1, 31, 10, 0)
        due, source = project_next_occurrence(
            anchor, "month", datetime(2026, 3, 1), interval_count=1,
        )
        self.assertEqual(due, datetime(2026, 3, 31, 10, 0))
        self.assertEqual(source, "projected_from_recorded_cycle")
        self.assertEqual(anchor, datetime(2026, 1, 31, 10, 0))

    def test_exact_window_enumerates_every_actual_occurrence(self):
        due = occurrences_between(
            datetime(2026, 8, 6, 9, 0),
            "week",
            datetime(2026, 8, 5),
            datetime(2026, 9, 4, 23, 59),
            interval_count=1,
        )
        self.assertEqual(
            due,
            [
                datetime(2026, 8, 6, 9, 0),
                datetime(2026, 8, 13, 9, 0),
                datetime(2026, 8, 20, 9, 0),
                datetime(2026, 8, 27, 9, 0),
                datetime(2026, 9, 3, 9, 0),
            ],
        )

    def test_window_honours_recurrence_end(self):
        due = occurrences_between(
            datetime(2026, 8, 1),
            "month",
            datetime(2026, 8, 1),
            datetime(2027, 1, 31),
            interval_count=1,
            recurrence_end_at=datetime(2026, 10, 1),
        )
        self.assertEqual(
            due,
            [datetime(2026, 8, 1), datetime(2026, 9, 1), datetime(2026, 10, 1)],
        )

    def test_lifecycle_effective_state_is_date_aware(self):
        now = datetime(2026, 8, 5)
        paused = SimpleNamespace(
            status="paused", is_active=True, paused_until=datetime(2026, 8, 10),
            recurrence_end_at=None, cancellation_effective_at=None,
        )
        cancelling = SimpleNamespace(
            status="cancelling", is_active=True, paused_until=None,
            recurrence_end_at=None, cancellation_effective_at=datetime(2026, 8, 5),
        )
        ended = SimpleNamespace(
            status="active", is_active=True, paused_until=None,
            recurrence_end_at=datetime(2026, 8, 4), cancellation_effective_at=None,
        )
        self.assertEqual(effective_status(paused, now), PaymentStatus.paused.value)
        self.assertEqual(effective_status(paused, datetime(2026, 8, 10)), "active")
        self.assertEqual(effective_status(cancelling, now), "cancelled")
        self.assertEqual(effective_status(ended, now), "ended")

    def test_invalid_cadence_and_unbounded_forecast_fail_closed(self):
        with self.assertRaises(ValueError):
            Cadence("month", 0)
        with self.assertRaises(ValueError):
            Cadence("month", 1.5)
        with self.assertRaises(ValueError):
            Cadence("fortnight", 1)
        with self.assertRaises(ValueError):
            occurrences_between(
                datetime(2026, 1, 1), "day", datetime(2026, 1, 1),
                datetime(2026, 1, 10), interval_count=1, limit=3,
            )


if __name__ == "__main__":
    unittest.main()
