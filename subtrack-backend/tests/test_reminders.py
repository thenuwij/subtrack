import os
import unittest
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.database import Base  # noqa: E402
from app.agent.finance import reminders_overview  # noqa: E402
from app.models import (  # noqa: E402
    AgentResearchCache,
    BillingCycle,
    Category,
    PaymentReminder,
    Subscription,
)
from app.routers.reminders import ReminderCreate, create_reminder  # noqa: E402
from app.routers.subscriptions import (  # noqa: E402
    MergeRequest,
    delete_subscription,
    merge_subscription,
)
from app.services.reminders import (  # noqa: E402
    list_user_reminders,
    reminder_payload,
    utcnow,
)
from app.services.schedules import project_next_occurrence  # noqa: E402


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_payment(
        self,
        name: str = "Cloud service",
        *,
        user_id: str = "owner",
        next_due: datetime | None = None,
        cycle: BillingCycle = BillingCycle.monthly,
        interval_unit: str | None = None,
        interval_count: int | None = None,
    ) -> Subscription:
        sub = Subscription(
            id=uuid4(), user_id=user_id, name=name,
            category=Category.software, amount=20, currency="AUD",
            converted_amount=20, cycle=cycle,
            interval_unit=interval_unit, interval_count=interval_count,
            next_due=next_due,
            is_active=True,
        )
        self.db.add(sub)
        self.db.commit()
        return sub

    def add_reminder(
        self,
        sub: Subscription,
        *,
        kind: str = "cancel",
        days_before: int = 7,
        target_date: datetime | None = None,
    ) -> PaymentReminder:
        reminder = PaymentReminder(
            id=uuid4(), user_id=sub.user_id, subscription_id=sub.id,
            kind=kind, days_before=days_before, target_date=target_date,
            is_active=True,
        )
        self.db.add(reminder)
        self.db.commit()
        return reminder

    def test_month_end_projection_preserves_the_calendar_intent(self):
        due, source = project_next_occurrence(
            datetime(2026, 1, 31), BillingCycle.monthly, datetime(2026, 2, 1),
        )
        self.assertEqual(due, datetime(2026, 2, 28))
        self.assertEqual(source, "projected_from_recorded_cycle")

    def test_a_due_date_today_does_not_jump_to_the_next_cycle(self):
        due, source = project_next_occurrence(
            datetime(2026, 8, 5), BillingCycle.monthly, datetime(2026, 8, 5, 23, 0),
        )
        self.assertEqual(due, datetime(2026, 8, 5))
        self.assertEqual(source, "recorded")

    def test_trial_reminder_requires_an_explicit_end_date(self):
        sub = self.add_payment(next_due=datetime.now() + timedelta(days=30))
        with self.assertRaises(HTTPException) as caught:
            create_reminder(
                ReminderCreate(
                    subscription_id=sub.id, kind="trial_end", days_before=7,
                ),
                user_id="owner",
                db=self.db,
            )
        self.assertEqual(caught.exception.status_code, 422)

    def test_reminder_creation_cannot_target_another_users_payment(self):
        private = self.add_payment(user_id="other", next_due=utcnow() + timedelta(days=30))
        with self.assertRaises(HTTPException) as caught:
            create_reminder(
                ReminderCreate(
                    subscription_id=private.id, kind="cancel", days_before=7,
                ),
                user_id="owner",
                db=self.db,
            )
        self.assertEqual(caught.exception.status_code, 404)

    def test_duplicate_active_reminders_are_rejected(self):
        sub = self.add_payment(next_due=utcnow() + timedelta(days=30))
        payload = ReminderCreate(
            subscription_id=sub.id, kind="cancel", days_before=7,
        )
        create_reminder(payload, user_id="owner", db=self.db)
        with self.assertRaises(HTTPException) as caught:
            create_reminder(payload, user_id="owner", db=self.db)
        self.assertEqual(caught.exception.status_code, 409)

    def test_dismissal_applies_to_one_recurring_occurrence_only(self):
        sub = self.add_payment(next_due=datetime(2026, 8, 10))
        reminder = self.add_reminder(sub)
        reminder.dismissed_for = datetime(2026, 8, 10)
        self.db.commit()

        current = reminder_payload(reminder, sub, datetime(2026, 8, 5))
        next_cycle = reminder_payload(reminder, sub, datetime(2026, 8, 11))

        self.assertEqual(current["status"], "dismissed")
        self.assertEqual(next_cycle["target_at"], "2026-09-10T00:00:00Z")
        self.assertNotEqual(next_cycle["status"], "dismissed")

    def test_quarterly_reminder_returns_on_the_next_quarter(self):
        sub = self.add_payment(
            next_due=datetime(2026, 8, 31),
            interval_unit="month",
            interval_count=3,
        )
        reminder = self.add_reminder(sub)
        reminder.dismissed_for = datetime(2026, 8, 31)
        self.db.commit()

        current = reminder_payload(reminder, sub, datetime(2026, 8, 20))
        next_quarter = reminder_payload(reminder, sub, datetime(2026, 9, 1))

        self.assertEqual(current["status"], "dismissed")
        self.assertEqual(next_quarter["target_at"], "2026-11-30T00:00:00Z")
        self.assertNotEqual(next_quarter["status"], "dismissed")

    def test_paused_without_resume_and_cancelled_reminders_are_not_listed(self):
        paused = self.add_payment(next_due=datetime(2026, 8, 10))
        paused.status = "paused"
        cancelled = self.add_payment(name="Cancelled", next_due=datetime(2026, 8, 11))
        cancelled.status = "cancelled"
        self.add_reminder(paused)
        self.add_reminder(cancelled)
        self.db.commit()

        rows = list_user_reminders(
            self.db, "owner", horizon_days=90, now=datetime(2026, 8, 5),
        )

        self.assertEqual(rows, [])

    def test_dashboard_listing_is_user_scoped_and_sorted_by_urgency(self):
        own = self.add_payment(next_due=datetime(2026, 8, 10))
        private = self.add_payment(
            name="Private", user_id="other", next_due=datetime(2026, 8, 7),
        )
        self.add_reminder(own, days_before=7)
        self.add_reminder(private, days_before=30)

        rows = list_user_reminders(
            self.db, "owner", horizon_days=90, now=datetime(2026, 8, 5),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["subscription_name"], "Cloud service")
        self.assertEqual(rows[0]["status"], "due")

    def test_assistant_reminder_tool_rechecks_visible_ids_against_user_ownership(self):
        own = self.add_payment(next_due=datetime(2026, 8, 10))
        private = self.add_payment(
            name="Private", user_id="other", next_due=datetime(2026, 8, 10),
        )
        own_reminder = self.add_reminder(own)
        private_reminder = self.add_reminder(private)

        result = reminders_overview(self.db, "owner", {
            "reminder_ids": [str(own_reminder.id), str(private_reminder.id)],
            "horizon_days": 730,
        })

        self.assertEqual(result["reminder_count"], 1)
        self.assertEqual(result["reminders"][0]["id"], str(own_reminder.id))
        self.assertIn("not enabled", result["delivery"])

    def test_deleting_a_payment_removes_its_reminders(self):
        sub = self.add_payment(next_due=utcnow() + timedelta(days=10))
        self.add_reminder(sub)
        self.db.add(AgentResearchCache(
            user_id="owner", subscription_id=sub.id, fingerprint="a" * 64,
            market="AU", result_json={"answer": "cached"},
            expires_at=utcnow() + timedelta(days=1),
        ))
        self.db.commit()

        delete_subscription(sub.id, user_id="owner", db=self.db)

        count = self.db.query(PaymentReminder).filter(
            PaymentReminder.subscription_id == sub.id,
        ).count()
        self.assertEqual(count, 0)
        self.assertEqual(
            self.db.query(AgentResearchCache).filter(
                AgentResearchCache.subscription_id == sub.id,
            ).count(),
            0,
        )

    def test_merging_duplicate_payments_preserves_one_equivalent_reminder(self):
        source = self.add_payment("Source", next_due=utcnow() + timedelta(days=10))
        target = self.add_payment("Target", next_due=source.next_due)
        self.add_reminder(source)
        self.add_reminder(target)
        self.db.add(AgentResearchCache(
            user_id="owner", subscription_id=source.id, fingerprint="b" * 64,
            market="AU", result_json={"answer": "cached"},
            expires_at=utcnow() + timedelta(days=1),
        ))
        self.db.commit()

        merge_subscription(
            source.id, MergeRequest(into=target.id), user_id="owner", db=self.db,
        )

        rows = self.db.query(PaymentReminder).filter(
            PaymentReminder.user_id == "owner",
            PaymentReminder.subscription_id == target.id,
            PaymentReminder.is_active == True,  # noqa: E712
        ).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            self.db.query(AgentResearchCache).filter(
                AgentResearchCache.subscription_id == source.id,
            ).count(),
            0,
        )


if __name__ == "__main__":
    unittest.main()
