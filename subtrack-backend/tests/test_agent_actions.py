import os
import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.agent.actions import (  # noqa: E402
    confirm_action,
    create_action_proposal,
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
    DuplicateDismissal,
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

    def test_assistant_add_supports_custom_quarterly_cadence(self):
        proposal = self.propose("propose_add_recurring_payment", {
            "name": "Quarterly hosting",
            "category": "cloud",
            "amount": 120,
            "currency": "AUD",
            "interval_unit": "month",
            "interval_count": 3,
            "next_due": self.future(30).isoformat(),
            "trial_ends_at": None,
            "recurrence_end_at": None,
            "status": "active",
            "paused_until": None,
            "cancellation_effective_at": None,
            "amount_type": "fixed",
            "spending_type": "optional",
        })

        completed = confirm_action(self.db, "owner", proposal["id"])
        sub = self.db.query(Subscription).one()

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(sub.interval_unit, "month")
        self.assertEqual(sub.interval_count, 3)
        self.assertEqual(sub.spending_type, "optional")
        self.assertEqual(financial_overview(self.db, "owner")["monthly_recurring_total"], 40)

    def test_assistant_recurring_reminder_keeps_a_null_fixed_target(self):
        sub = self.add_payment()
        proposal = self.propose("propose_add_payment_reminder", {
            "subscription_id": str(sub.id),
            "kind": "renewal",
            "days_before": 5,
            "target_date": None,
            "note": "Check whether I still use this",
        })

        confirm_action(self.db, "owner", proposal["id"])
        reminder = self.db.query(PaymentReminder).one()

        self.assertIsNone(reminder.target_date)
        self.assertEqual(reminder.days_before, 5)

    def test_assistant_can_pause_and_explicitly_clear_lifecycle_dates(self):
        sub = self.add_payment()
        paused_until = self.future(45)
        pause = self.propose("propose_update_recurring_payment", {
            "subscription_id": str(sub.id),
            "status": "paused",
            "paused_until": paused_until.isoformat(),
        })
        confirm_action(self.db, "owner", pause["id"])
        self.db.refresh(sub)
        self.assertEqual(sub.status, "paused")
        self.assertEqual(sub.paused_until.date(), paused_until.date())

        # Use a fresh assistant message because proposal fingerprints are scoped
        # to the response that generated them in the real UI.
        self.message = AgentMessage(
            id=uuid4(), thread_id=self.thread.id, user_id="owner",
            role="assistant", sequence=2, content="", status="streaming",
        )
        self.db.add(self.message)
        self.db.commit()
        resume = self.propose("propose_update_recurring_payment", {
            "subscription_id": str(sub.id),
            "status": "active",
            "clear_fields": ["paused_until"],
        })
        confirm_action(self.db, "owner", resume["id"])
        self.db.refresh(sub)
        self.assertEqual(sub.status, "active")
        self.assertIsNone(sub.paused_until)

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

    def test_duplicate_false_positive_requires_confirmation_and_replays_safely(self):
        first = self.add_payment("Canva Pro")
        second = self.add_payment("Canva Teams")

        proposal = self.propose("propose_dismiss_duplicate_suggestion", {
            "subscription_id": str(first.id),
            "possible_duplicate_id": str(second.id),
        })
        self.assertEqual(proposal["status"], "pending")
        self.assertEqual(self.db.query(DuplicateDismissal).count(), 0)

        completed = confirm_action(self.db, "owner", proposal["id"])
        replayed = confirm_action(self.db, "owner", proposal["id"])

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(replayed["result"], completed["result"])
        self.assertEqual(self.db.query(DuplicateDismissal).count(), 1)

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
            interval_unit="month", interval_count=1, cadence_confidence="medium",
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

    def test_approval_clear_fields_is_inert_confirmed_and_idempotent(self):
        trial_end = self.future(21)
        created = create_subscription(
            SubscriptionCreate(
                name="Old trial", category=Category.software, amount=24,
                currency="AUD", cycle=BillingCycle.monthly,
                trial_ends_at=trial_end,
            ),
            user_id="owner",
            db=self.db,
        )
        sub = self.db.query(Subscription).filter(
            Subscription.id == UUID(created["id"]),
        ).one()
        detection = DetectedSubscription(
            id=uuid4(), user_id="owner", merchant="Old trial",
            sender_domain="old-trial.test", product_key="old-trial",
            category=Category.software, cycle=BillingCycle.monthly,
            interval_unit="month", interval_count=1, cadence_confidence="high",
            amount=24, currency="AUD", confidence="high", charge_count=0,
            next_due=trial_end, trial_ends_at=trial_end,
            existing_subscription_id=sub.id, status=DetectionStatus.pending,
        )
        self.db.add(detection)
        self.db.commit()

        proposal = self.propose("propose_approve_inbox_detection", {
            "detection_id": str(detection.id),
            "amount": None,
            "duplicate_resolution": None,
            "clear_fields": ["next_due", "trial_ends_at"],
        })

        # A model tool call only creates a reviewable proposal. The saved dates
        # and automatic reminder remain untouched until authenticated confirm.
        self.db.refresh(sub)
        self.assertEqual(proposal["status"], "pending")
        self.assertEqual(sub.next_due.date(), trial_end.date())
        self.assertEqual(sub.trial_ends_at.date(), trial_end.date())
        self.assertEqual(
            self.db.query(PaymentReminder).filter(
                PaymentReminder.subscription_id == sub.id,
                PaymentReminder.is_active.is_(True),
            ).count(),
            1,
        )
        self.assertIn("saved next due date will be cleared", proposal["description"])
        self.assertIn("saved trial end", proposal["description"])
        self.assertNotIn("will also be saved", proposal["description"])

        completed = confirm_action(self.db, "owner", proposal["id"])
        replayed = confirm_action(self.db, "owner", proposal["id"])
        self.db.refresh(sub)
        self.db.refresh(detection)

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(replayed["result"], completed["result"])
        self.assertIsNone(sub.next_due)
        self.assertIsNone(sub.trial_ends_at)
        self.assertEqual(detection.status, DetectionStatus.approved)
        reminder = self.db.query(PaymentReminder).filter(
            PaymentReminder.subscription_id == sub.id,
        ).one()
        self.assertFalse(reminder.is_active)

    def test_approval_can_clear_next_due_without_clearing_other_fields(self):
        sub = self.add_payment("Dated service")
        old_due = self.future(18)
        sub.next_due = old_due
        detection = DetectedSubscription(
            id=uuid4(), user_id="owner", merchant="Dated service",
            sender_domain="dated.test", product_key="dated-service",
            category=Category.software, cycle=BillingCycle.monthly,
            interval_unit="month", interval_count=1, cadence_confidence="high",
            amount=20, currency="AUD", confidence="high", charge_count=1,
            next_due=old_due, existing_subscription_id=sub.id,
            status=DetectionStatus.pending,
        )
        self.db.add(detection)
        self.db.commit()

        proposal = self.propose("propose_approve_inbox_detection", {
            "detection_id": str(detection.id),
            "amount": None,
            "duplicate_resolution": None,
            "clear_fields": ["next_due"],
        })
        confirm_action(self.db, "owner", proposal["id"])
        self.db.refresh(sub)

        self.assertIsNone(sub.next_due)
        self.assertEqual(sub.name, "Dated service")
        self.assertEqual(sub.amount, 20)

    def test_approval_clear_fields_is_allow_listed_and_non_conflicting(self):
        detection = DetectedSubscription(
            id=uuid4(), user_id="owner", merchant="Safe service",
            sender_domain="safe.test", product_key="safe-service",
            category=Category.software, cycle=BillingCycle.monthly,
            interval_unit="month", interval_count=1, cadence_confidence="high",
            amount=20, currency="AUD", confidence="high", charge_count=1,
            status=DetectionStatus.pending,
        )
        self.db.add(detection)
        self.db.commit()

        with self.assertRaises(ValidationError):
            self.propose("propose_approve_inbox_detection", {
                "detection_id": str(detection.id),
                "clear_fields": ["amount"],
            })
        with self.assertRaises(ValidationError):
            self.propose("propose_approve_inbox_detection", {
                "detection_id": str(detection.id),
                "next_due": self.future(14).isoformat(),
                "clear_fields": ["next_due"],
            })

    def test_approval_cannot_claim_to_clear_due_date_while_retaining_trial(self):
        detection = DetectedSubscription(
            id=uuid4(), user_id="owner", merchant="Trial service",
            sender_domain="trial.test", product_key="trial-service",
            category=Category.software, cycle=BillingCycle.monthly,
            interval_unit="month", interval_count=1, cadence_confidence="high",
            amount=20, currency="AUD", confidence="high", charge_count=0,
            next_due=self.future(14), trial_ends_at=self.future(14),
            status=DetectionStatus.pending,
        )
        self.db.add(detection)
        self.db.commit()

        with self.assertRaises(HTTPException) as caught:
            self.propose("propose_approve_inbox_detection", {
                "detection_id": str(detection.id),
                "clear_fields": ["next_due"],
            })
        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("Clear trial_ends_at as well", str(caught.exception.detail))

    def test_legacy_approval_payload_without_clear_fields_still_confirms(self):
        trial_end = self.future(12)
        detection = DetectedSubscription(
            id=uuid4(), user_id="owner", merchant="Legacy trial",
            sender_domain="legacy.test", product_key="legacy-trial",
            category=Category.software, cycle=BillingCycle.monthly,
            interval_unit="month", interval_count=1, cadence_confidence="high",
            amount=15, currency="AUD", confidence="high", charge_count=0,
            next_due=trial_end, trial_ends_at=trial_end,
            status=DetectionStatus.pending,
        )
        self.db.add(detection)
        self.db.commit()
        proposal = self.propose("propose_approve_inbox_detection", {
            "detection_id": str(detection.id),
        })
        action = self.db.query(AgentAction).filter(
            AgentAction.id == UUID(proposal["id"]),
        ).one()
        action.payload_json = {
            key: value
            for key, value in action.payload_json.items()
            if key != "clear_fields"
        }
        self.db.commit()

        confirm_action(self.db, "owner", proposal["id"])
        sub = self.db.query(Subscription).filter(
            Subscription.name == "Legacy trial",
        ).one()

        self.assertEqual(sub.next_due.date(), trial_end.date())
        self.assertEqual(sub.trial_ends_at.date(), trial_end.date())

    def test_another_users_detection_cannot_be_cleared_or_approved(self):
        detection = DetectedSubscription(
            id=uuid4(), user_id="someone-else", merchant="Private trial",
            sender_domain="private.test", product_key="private-trial",
            category=Category.software, cycle=BillingCycle.monthly,
            interval_unit="month", interval_count=1, cadence_confidence="high",
            amount=15, currency="AUD", confidence="high", charge_count=0,
            next_due=self.future(12), trial_ends_at=self.future(12),
            status=DetectionStatus.pending,
        )
        self.db.add(detection)
        self.db.commit()

        with self.assertRaises(HTTPException) as caught:
            self.propose("propose_approve_inbox_detection", {
                "detection_id": str(detection.id),
                "clear_fields": ["next_due", "trial_ends_at"],
            })
        self.assertEqual(caught.exception.status_code, 404)

    def test_assistant_can_correct_unknown_gmail_cadence_before_approval(self):
        detection = DetectedSubscription(
            id=uuid4(), user_id="owner", merchant="Quarterly service",
            sender_domain="quarterly.test", product_key="quarterly-service",
            category=Category.software, cycle=BillingCycle.monthly,
            cadence_confidence="unknown",
            amount=90, currency="AUD", confidence="medium", charge_count=1,
            status=DetectionStatus.pending,
        )
        self.db.add(detection)
        self.db.commit()

        with self.assertRaises(HTTPException) as missing:
            self.propose("propose_approve_inbox_detection", {
                "detection_id": str(detection.id),
                "amount": None,
                "duplicate_resolution": None,
            })
        self.assertEqual(missing.exception.status_code, 422)

        proposal = self.propose("propose_approve_inbox_detection", {
            "detection_id": str(detection.id),
            "amount": None,
            "interval_unit": "month",
            "interval_count": 3,
            "amount_type": "fixed",
            "duplicate_resolution": None,
        })
        confirm_action(self.db, "owner", proposal["id"])

        sub = self.db.query(Subscription).filter(
            Subscription.name == "Quarterly service",
        ).one()
        self.assertEqual(sub.interval_unit, "month")
        self.assertEqual(sub.interval_count, 3)
        self.assertEqual(detection.status, DetectionStatus.approved)

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
            interval_unit="month", interval_count=1, cadence_confidence="medium",
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
        created = create_subscription(
            SubscriptionCreate(
                name="Canva trial", category=Category.software, amount=17.99,
                currency="AUD", cycle=BillingCycle.monthly,
                trial_ends_at=trial_end,
            ),
            user_id="owner",
            db=self.db,
        )
        sub = self.db.query(Subscription).filter(
            Subscription.id == UUID(created["id"]),
        ).one()
        detection = DetectedSubscription(
            id=uuid4(), user_id="owner", merchant="Canva Pro",
            sender_domain="canva.com", product_key="canva-pro",
            category=Category.software, cycle=BillingCycle.monthly,
            interval_unit="month", interval_count=1, cadence_confidence="medium",
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
        created = create_subscription(
            SubscriptionCreate(
                name="Canva Pro", category=Category.software, amount=17.99,
                currency="AUD", cycle=BillingCycle.monthly,
                trial_ends_at=self.future(10),
            ),
            user_id="owner",
            db=self.db,
        )
        sub = self.db.query(Subscription).filter(
            Subscription.id == UUID(created["id"]),
        ).one()
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
