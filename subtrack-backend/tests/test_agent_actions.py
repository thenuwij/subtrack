import os
import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.agent.actions import (  # noqa: E402
    create_action_proposal,
    confirm_action,
    reject_action,
)
from app.agent.finance import financial_overview  # noqa: E402
from app.database import Base  # noqa: E402
from app.gmail.analyzer import DetectedSubscription as AnalyzedSubscription  # noqa: E402
from app.models import (  # noqa: E402
    AgentAction,
    AgentMessage,
    AgentThread,
    BillingCycle,
    Category,
    DetectedSubscription,
    DetectionStatus,
    PaymentReminder,
    Subscription,
)
from app.routers.detected import ApproveOverrides, approve  # noqa: E402
from app.routers.gmail import _apply_detections  # noqa: E402
from app.routers.subscriptions import SubscriptionCreate, create_subscription  # noqa: E402


class AgentActionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.thread = AgentThread(
            id=uuid4(), user_id="owner", title="Actions", next_message_sequence=1,
        )
        self.message = AgentMessage(
            id=uuid4(), thread_id=self.thread.id, user_id="owner",
            role="assistant", sequence=1, content="", status="streaming",
        )
        self.db.add_all([self.thread, self.message])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_payment(self, name="Cloud", user_id="owner") -> Subscription:
        sub = Subscription(
            id=uuid4(), user_id=user_id, name=name, category=Category.software,
            amount=20, currency="AUD", converted_amount=20,
            cycle=BillingCycle.monthly, next_due=datetime(2026, 9, 1),
            is_active=True,
        )
        self.db.add(sub)
        self.db.commit()
        return sub

    @staticmethod
    def future(days: int) -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=days)

    def propose(self, name: str, payload: dict) -> dict:
        return create_action_proposal(
            name, payload, self.db, "owner",
            thread_id=self.thread.id,
            assistant_message_id=self.message.id,
        )

    def test_proposal_is_inert_and_confirmation_is_idempotent(self):
        proposal = self.propose("propose_add_recurring_payment", {
            "name": "Design tool", "category": "software", "amount": 18,
            "currency": "AUD", "cycle": "monthly", "next_due": None,
            "trial_ends_at": None,
        })
        self.assertEqual(self.db.query(Subscription).count(), 0)
        self.assertEqual(proposal["status"], "pending")

        completed = confirm_action(self.db, "owner", proposal["id"])
        repeated = confirm_action(self.db, "owner", proposal["id"])

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(repeated["result"], completed["result"])
        self.assertEqual(self.db.query(Subscription).count(), 1)

    def test_another_user_cannot_confirm_an_action(self):
        proposal = self.propose("propose_add_recurring_payment", {
            "name": "Private", "category": "other", "amount": 8,
            "currency": "AUD", "cycle": "monthly", "next_due": None,
            "trial_ends_at": None,
        })
        with self.assertRaises(HTTPException) as caught:
            confirm_action(self.db, "other-user", proposal["id"])
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(self.db.query(Subscription).count(), 0)

    def test_rejected_action_never_mutates_data(self):
        proposal = self.propose("propose_add_recurring_payment", {
            "name": "No thanks", "category": "other", "amount": 8,
            "currency": "AUD", "cycle": "monthly", "next_due": None,
            "trial_ends_at": None,
        })
        rejected = reject_action(self.db, "owner", proposal["id"])
        self.assertEqual(rejected["status"], "rejected")
        with self.assertRaises(HTTPException):
            confirm_action(self.db, "owner", proposal["id"])
        self.assertEqual(self.db.query(Subscription).count(), 0)

    def test_stale_payment_blocks_a_proposed_update(self):
        sub = self.add_payment()
        proposal = self.propose("propose_update_recurring_payment", {
            "subscription_id": str(sub.id), "name": None, "category": None,
            "amount": 25, "currency": None, "cycle": None, "next_due": None,
        })
        sub.name = "Changed elsewhere"
        self.db.commit()

        with self.assertRaises(HTTPException) as caught:
            confirm_action(self.db, "owner", proposal["id"])
        self.assertEqual(caught.exception.status_code, 409)
        action = self.db.query(AgentAction).filter(AgentAction.id == UUID(proposal["id"])).one()
        self.assertEqual(action.status, "failed")
        self.assertEqual(sub.amount, 20)

    def test_marking_a_trial_creates_the_shared_dashboard_reminder(self):
        sub = self.add_payment()
        trial_end = self.future(21)
        proposal = self.propose("propose_mark_payment_as_free_trial", {
            "subscription_id": str(sub.id),
            "trial_ends_at": trial_end.isoformat(),
            "price_after_trial": 30,
        })
        confirm_action(self.db, "owner", proposal["id"])
        self.db.refresh(sub)

        reminder = self.db.query(PaymentReminder).filter(
            PaymentReminder.subscription_id == sub.id,
            PaymentReminder.kind == "trial_end",
            PaymentReminder.is_active == True,  # noqa: E712
        ).one()
        self.assertEqual(sub.trial_ends_at.date(), trial_end.date())
        self.assertEqual(sub.next_due.date(), trial_end.date())
        self.assertEqual(reminder.target_date.date(), trial_end.date())
        self.assertEqual(reminder.days_before, 7)

    def test_merge_retargets_pending_gmail_duplicate_hint(self):
        target = self.add_payment("Canva Pro")
        source = self.add_payment("Canva")
        detection = DetectedSubscription(
            id=uuid4(), user_id="owner", merchant="Canva Teams",
            sender_domain="canva.com", product_key="canva-teams",
            category=Category.software, cycle=BillingCycle.monthly,
            amount=30, currency="AUD", confidence="medium", charge_count=1,
            similar_subscription_id=source.id, similar_reason="Likely duplicate",
            status=DetectionStatus.pending,
        )
        self.db.add(detection)
        self.db.commit()

        proposal = self.propose("propose_merge_recurring_payments", {
            "source_subscription_id": str(source.id),
            "target_subscription_id": str(target.id),
        })
        confirm_action(self.db, "owner", proposal["id"])
        self.db.refresh(detection)

        self.assertEqual(detection.similar_subscription_id, target.id)
        self.assertIsNone(self.db.get(Subscription, source.id))

    def test_remove_detaches_pending_gmail_links(self):
        sub = self.add_payment("Old record")
        detection = DetectedSubscription(
            id=uuid4(), user_id="owner", merchant="Old record",
            sender_domain="example.com", product_key="old",
            category=Category.other, cycle=BillingCycle.monthly,
            amount=9, currency="AUD", confidence="medium", charge_count=1,
            existing_subscription_id=sub.id, status=DetectionStatus.pending,
        )
        self.db.add(detection)
        self.db.commit()

        proposal = self.propose("propose_remove_recurring_payment", {
            "subscription_id": str(sub.id),
        })
        confirm_action(self.db, "owner", proposal["id"])
        self.db.refresh(detection)

        self.assertIsNone(detection.existing_subscription_id)

    def test_detected_update_target_is_rechecked_at_confirmation(self):
        sub = self.add_payment("Cloud")
        detection = DetectedSubscription(
            id=uuid4(), user_id="owner", merchant="Cloud Plus",
            sender_domain="cloud.test", product_key="cloud-plus",
            category=Category.software, cycle=BillingCycle.monthly,
            amount=25, currency="AUD", confidence="high", charge_count=2,
            existing_subscription_id=sub.id, status=DetectionStatus.pending,
        )
        self.db.add(detection)
        self.db.commit()
        proposal = self.propose("propose_approve_inbox_detection", {
            "detection_id": str(detection.id),
            "amount": None,
            "duplicate_resolution": None,
        })
        sub.name = "Changed while reviewing"
        self.db.commit()

        with self.assertRaises(HTTPException) as caught:
            confirm_action(self.db, "owner", proposal["id"])
        self.assertEqual(caught.exception.status_code, 409)
        self.db.refresh(detection)
        self.assertEqual(detection.status, DetectionStatus.pending)

    def test_active_trial_is_excluded_from_current_paid_total(self):
        create_subscription(
            SubscriptionCreate(
                name="Canva trial", category=Category.software, amount=20,
                currency="AUD", cycle=BillingCycle.monthly,
                trial_ends_at=self.future(14),
            ),
            user_id="owner",
            db=self.db,
        )
        overview = financial_overview(self.db, "owner")
        self.assertEqual(overview["monthly_recurring_total"], 0.0)
        self.assertEqual(overview["active_trial_count"], 1)
        self.assertEqual(self.db.query(PaymentReminder).count(), 1)

    def test_approving_a_detected_trial_preserves_it_and_adds_reminder(self):
        detection = DetectedSubscription(
            id=uuid4(), user_id="owner", merchant="Canva Pro",
            sender_domain="canva.com", product_key="canva-pro",
            category=Category.software, cycle=BillingCycle.monthly,
            amount=0, currency="AUD", confidence="medium", charge_count=0,
            trial_ends_at=self.future(10),
            status=DetectionStatus.pending,
        )
        self.db.add(detection)
        self.db.commit()

        result = approve(
            detection.id,
            ApproveOverrides(amount=17.99),
            user_id="owner",
            db=self.db,
        )
        sub = self.db.query(Subscription).filter(
            Subscription.id == UUID(result["subscription_id"]),
        ).one()
        self.assertEqual(sub.amount, 17.99)
        self.assertIsNotNone(sub.trial_ends_at)
        self.assertEqual(
            self.db.query(PaymentReminder).filter(
                PaymentReminder.subscription_id == sub.id,
            ).count(),
            1,
        )

    def test_first_successful_charge_clears_automatic_trial_reminder(self):
        trial_end = self.future(10)
        sub = create_subscription(
            SubscriptionCreate(
                name="Canva trial", category=Category.software, amount=17.99,
                currency="AUD", cycle=BillingCycle.monthly,
                trial_ends_at=trial_end,
            ),
            user_id="owner",
            db=self.db,
        )
        detection = DetectedSubscription(
            id=uuid4(), user_id="owner", merchant="Canva Pro",
            sender_domain="canva.com", product_key="canva-pro",
            category=Category.software, cycle=BillingCycle.monthly,
            amount=17.99, currency="AUD", confidence="high", charge_count=1,
            existing_subscription_id=sub.id, status=DetectionStatus.pending,
        )
        self.db.add(detection)
        self.db.commit()

        approve(detection.id, ApproveOverrides(), user_id="owner", db=self.db)
        self.db.refresh(sub)
        reminder = self.db.query(PaymentReminder).filter(
            PaymentReminder.subscription_id == sub.id,
        ).one()

        self.assertIsNone(sub.trial_ends_at)
        self.assertFalse(reminder.is_active)

    def test_gmail_surfaces_a_same_price_trial_conversion_for_review(self):
        sub = create_subscription(
            SubscriptionCreate(
                name="Canva Pro", category=Category.software, amount=17.99,
                currency="AUD", cycle=BillingCycle.monthly,
                trial_ends_at=self.future(10),
            ),
            user_id="owner",
            db=self.db,
        )
        sub.source_domain = "canva.com"
        sub.source_key = "canva-pro"
        self.db.commit()
        found = AnalyzedSubscription(
            sender_domain="canva.com", merchant="Canva Pro",
            product_key="canva-pro", category="software", cycle="monthly",
            amount=17.99, currency="AUD", previous_amount=None,
            cancelled=False, confidence="high", charge_count=1,
            trial_ends_at=None,
        )

        existing: list[DetectedSubscription] = []
        _apply_detections(self.db, "owner", [sub], existing, [found])
        self.db.flush()

        self.assertEqual(len(existing), 1)
        self.assertEqual(existing[0].existing_subscription_id, sub.id)
        self.assertIsNone(existing[0].trial_ends_at)


if __name__ == "__main__":
    unittest.main()
