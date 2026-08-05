import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.models import (
    AgentMessage,
    AgentThread,
    DetectedSubscription,
    DuplicateDismissal,
    GmailAccount,
    PaymentReminder,
    Subscription,
    SubscriptionChange,
)


def _index_columns(model) -> dict[str, tuple[str, ...]]:
    return {
        index.name: tuple(column.name for column in index.columns)
        for index in model.__table__.indexes
    }


class ProductionIndexContractTests(unittest.TestCase):
    def test_hot_queries_and_foreign_keys_have_stable_composite_indexes(self):
        expected = {
            Subscription: {
                "ix_subscriptions_user_active_name": ("user_id", "is_active", "name"),
            },
            SubscriptionChange: {
                "ix_subscription_changes_user_changed": ("user_id", "changed_at"),
            },
            GmailAccount: {
                "ix_gmail_accounts_scan_started": ("scan_status", "scan_started_at"),
            },
            DetectedSubscription: {
                "ix_detected_subscriptions_user_status_charge": (
                    "user_id",
                    "status",
                    "charge_count",
                    "detected_at",
                ),
            },
            PaymentReminder: {
                "ix_payment_reminders_user_active_created": (
                    "user_id",
                    "is_active",
                    "created_at",
                ),
            },
            AgentThread: {
                "ix_agent_threads_user_archived_updated": (
                    "user_id",
                    "archived",
                    "updated_at",
                ),
            },
            AgentMessage: {
                "ix_agent_messages_user_role_created": (
                    "user_id",
                    "role",
                    "created_at",
                ),
                "ix_agent_messages_status_updated": ("status", "updated_at"),
                "ix_agent_messages_reply_sequence": ("reply_to_id", "sequence"),
            },
            DuplicateDismissal: {
                "ix_duplicate_dismissals_subscription_a": ("subscription_a_id",),
                "ix_duplicate_dismissals_subscription_b": ("subscription_b_id",),
            },
        }

        for model, wanted in expected.items():
            actual = _index_columns(model)
            for name, columns in wanted.items():
                with self.subTest(model=model.__name__, index=name):
                    self.assertEqual(actual.get(name), columns)


if __name__ == "__main__":
    unittest.main()
