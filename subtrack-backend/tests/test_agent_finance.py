import os
import unittest
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.agent.finance import (  # noqa: E402
    commitment_changes,
    financial_overview,
    list_payments,
    payment_detail,
    review_detections,
    upcoming_charges,
)
from app.database import Base  # noqa: E402
from app.models import (  # noqa: E402
    BillingCycle,
    Category,
    ChangeKind,
    DetectedSubscription,
    DetectionStatus,
    Subscription,
    SubscriptionChange,
    UserPreference,
)


class AgentFinanceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.db.add(UserPreference(
            user_id="owner", base_currency="AUD", monthly_income=1_000,
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_payment(
        self,
        name: str,
        amount: float,
        cycle: BillingCycle = BillingCycle.monthly,
        *,
        user_id: str = "owner",
        category: Category = Category.software,
        currency: str = "AUD",
        converted_amount: float | None = None,
        next_due: datetime | None = None,
    ) -> Subscription:
        sub = Subscription(
            id=uuid4(), user_id=user_id, name=name, category=category,
            amount=amount, currency=currency, converted_amount=converted_amount,
            cycle=cycle, next_due=next_due, is_active=True,
        )
        self.db.add(sub)
        self.db.commit()
        return sub

    def test_overview_normalises_cycles_categories_and_income_share(self):
        self.add_payment("Monthly", 120, category=Category.software)
        self.add_payment("Weekly", 12, BillingCycle.weekly, category=Category.food)
        self.add_payment("Annual", 120, BillingCycle.yearly, category=Category.software)

        overview = financial_overview(self.db, "owner")

        self.assertEqual(overview["monthly_recurring_total"], 182.0)
        self.assertEqual(overview["yearly_recurring_total"], 2184.0)
        self.assertEqual(overview["recurring_share_of_income_percent"], 18.2)
        self.assertEqual(overview["currency_conversion"]["status"], "exact")
        self.assertIn("not a bank-transaction ledger", overview["scope"])
        self.assertEqual(overview["categories"][0]["monthly"], 130.0)

    def test_all_queries_are_scoped_to_the_authenticated_user(self):
        own = self.add_payment("Mine", 10)
        other = self.add_payment("Private", 999, user_id="other-user")

        listed = list_payments(self.db, "owner", {"limit": 100})
        self.assertEqual([row["name"] for row in listed["payments"]], ["Mine"])
        self.assertTrue(payment_detail(self.db, "owner", str(own.id))["found"])
        self.assertFalse(payment_detail(self.db, "owner", str(other.id))["found"])

    def test_selected_ids_are_hints_and_cannot_cross_user_boundaries(self):
        own = self.add_payment("Mine", 10)
        other = self.add_payment("Private", 999, user_id="other-user")

        result = list_payments(self.db, "owner", {
            "subscription_ids": [str(own.id), str(other.id)],
        })

        self.assertEqual([row["id"] for row in result["payments"]], [str(own.id)])

    def test_past_due_dates_are_projected_without_changing_the_record(self):
        monthly = self.add_payment(
            "Month end", 20, next_due=datetime(2026, 6, 30, 9, 0),
        )
        self.add_payment(
            "Weekly", 5, BillingCycle.weekly,
            next_due=datetime(2026, 7, 30, 9, 0),
        )
        self.add_payment("Unknown date", 7)

        result = upcoming_charges(
            self.db, "owner", 30, now=datetime(2026, 8, 5, 8, 0),
        )

        self.assertEqual([row["name"] for row in result["charges"]], ["Weekly", "Month end"])
        self.assertEqual(result["charges"][1]["due_at"], "2026-08-30T09:00:00")
        self.assertEqual(result["charges"][1]["due_date_source"], "projected_from_recorded_cycle")
        self.assertEqual(result["missing_due_date_count"], 1)
        self.assertEqual(monthly.next_due, datetime(2026, 6, 30, 9, 0))

    def test_commitment_change_is_monthly_and_excludes_other_users(self):
        sub = self.add_payment("Changed", 15)
        self.db.add_all([
            SubscriptionChange(
                id=uuid4(), user_id="owner", subscription_id=sub.id,
                name="Changed", kind=ChangeKind.price_change,
                old_monthly=10, new_monthly=15, currency="AUD",
                changed_at=datetime(2026, 8, 2),
            ),
            SubscriptionChange(
                id=uuid4(), user_id="other-user", subscription_id=uuid4(),
                name="Private", kind=ChangeKind.added,
                old_monthly=None, new_monthly=500, currency="AUD",
                changed_at=datetime(2026, 8, 3),
            ),
        ])
        self.db.commit()

        result = commitment_changes(
            self.db, "owner", "current_month", now=datetime(2026, 8, 5),
        )

        self.assertEqual(result["net_monthly_commitment_change"], 5.0)
        self.assertEqual(len(result["changes"]), 1)
        self.assertEqual(result["changes"][0]["delta_monthly_in_base"], 5.0)

    def test_foreign_currency_never_silently_equals_the_base_currency(self):
        self.add_payment("USD service", 65, currency="USD")
        with patch("app.agent.finance.get_cached_rate_snapshot", return_value=None):
            overview = financial_overview(self.db, "owner")

        self.assertEqual(overview["monthly_recurring_total"], 0.0)
        self.assertEqual(overview["currency_conversion"]["status"], "incomplete")
        self.assertEqual(overview["unconverted_payments"][0]["currency"], "USD")

    def test_cached_current_rate_converts_foreign_currency(self):
        self.add_payment("USD service", 65, currency="USD")
        snapshot = {
            "base": "AUD", "rates": {"USD": 0.65}, "cached": True,
            "stale": False, "fetched_at": "2026-08-05T00:00:00",
        }
        with patch("app.agent.finance.get_cached_rate_snapshot", return_value=snapshot):
            overview = financial_overview(self.db, "owner")

        self.assertEqual(overview["monthly_recurring_total"], 100.0)
        self.assertEqual(overview["currency_conversion"]["status"], "current_rates")
        self.assertEqual(overview["currency_conversion"]["rates_as_of"], "2026-08-05T00:00:00")

    def test_review_queue_only_returns_the_users_unapproved_findings(self):
        own = DetectedSubscription(
            id=uuid4(), user_id="owner", merchant="Cloud tool",
            sender_domain="cloud.example", product_key="cloud-tool",
            category=Category.software, cycle=BillingCycle.monthly,
            amount=20, currency="AUD", confidence="high", charge_count=3,
            status=DetectionStatus.pending,
        )
        other = DetectedSubscription(
            id=uuid4(), user_id="other-user", merchant="Private",
            sender_domain="private.example", product_key="private",
            category=Category.other, cycle=BillingCycle.monthly,
            amount=999, currency="AUD", confidence="high", charge_count=2,
            status=DetectionStatus.pending,
        )
        self.db.add_all([own, other])
        self.db.commit()

        result = review_detections(self.db, "owner", {
            "detection_ids": [str(own.id), str(other.id)],
            "status": "pending",
        })

        self.assertEqual([row["merchant"] for row in result["detections"]], ["Cloud tool"])
        self.assertTrue(result["requires_user_review"])
        self.assertIn("excluded from recurring totals", result["scope"])


if __name__ == "__main__":
    unittest.main()
