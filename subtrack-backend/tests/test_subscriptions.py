import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.database import Base  # noqa: E402
from app.models import (  # noqa: E402
    BillingCycle,
    Category,
    DuplicateDismissal,
    ExchangeRateSnapshot,
    Subscription,
    SubscriptionChange,
    UserPreference,
)
from app.routers import rates as rates_router  # noqa: E402
from app.routers.subscriptions import (  # noqa: E402
    DismissDuplicateRequest,
    EquivalencePreview,
    SubscriptionCreate,
    SubscriptionUpdate,
    create_subscription,
    dismiss_duplicate_suggestion,
    get_duplicates,
    get_subscriptions,
    preview_equivalents,
    subscription_payload,
    update_subscription,
)


class SubscriptionContractTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.db.add(UserPreference(user_id="owner", base_currency="AUD"))
        self.db.commit()
        with rates_router._cache_lock:
            rates_router._cache.clear()
        from app.routers import subscriptions as subscriptions_router
        with subscriptions_router._duplicate_cache_lock:
            subscriptions_router._duplicate_cache.clear()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        with rates_router._cache_lock:
            rates_router._cache.clear()
        from app.routers import subscriptions as subscriptions_router
        with subscriptions_router._duplicate_cache_lock:
            subscriptions_router._duplicate_cache.clear()

    def create(self, **overrides) -> Subscription:
        values = {
            "name": "Quarterly service",
            "category": Category.software,
            "amount": 120,
            "currency": "AUD",
            "interval_unit": "month",
            "interval_count": 3,
            "next_due": datetime.now() + timedelta(days=30),
        }
        values.update(overrides)
        payload = create_subscription(
            SubscriptionCreate(**values), user_id="owner", db=self.db,
        )
        return self.db.get(Subscription, UUID(payload["id"]))

    def test_custom_cadence_persists_with_legacy_compatibility_and_equivalents(self):
        sub = self.create()
        payload = subscription_payload(sub)

        self.assertEqual(sub.interval_unit, "month")
        self.assertEqual(sub.interval_count, 3)
        self.assertEqual(sub.cycle, BillingCycle.monthly)
        self.assertEqual(payload["cadence_label"], "Every 3 months")
        self.assertEqual(payload["monthly_equivalent"], 40)
        self.assertEqual(payload["yearly_equivalent"], 480)

    def test_legacy_inactive_create_does_not_reactivate_the_payment(self):
        payload = create_subscription(
            SubscriptionCreate(
                name="Old client", category=Category.other, amount=10,
                currency="AUD", cycle=BillingCycle.monthly, is_active=False,
            ),
            user_id="owner",
            db=self.db,
        )

        self.assertFalse(payload["is_active"])
        self.assertEqual(payload["status"], "cancelled")

    def test_shared_bill_keeps_full_cost_and_normalises_only_the_users_share(self):
        sub = self.create(
            name="Shared internet", amount=120, full_amount=300, share_ratio=0.4,
            interval_unit="month", interval_count=1,
        )
        payload = subscription_payload(sub)

        self.assertEqual(sub.amount, 120)
        self.assertEqual(sub.full_amount, 300)
        self.assertEqual(sub.split_mode, "ratio")
        self.assertEqual(payload["monthly_equivalent"], 120)

    def test_lifecycle_dates_can_be_explicitly_cleared(self):
        future = datetime.now() + timedelta(days=90)
        sub = self.create(
            status="paused",
            paused_until=future,
            recurrence_end_at=future + timedelta(days=90),
            cancellation_effective_at=future + timedelta(days=30),
        )

        updated = update_subscription(
            sub.id,
            SubscriptionUpdate(
                status="active",
                paused_until=None,
                recurrence_end_at=None,
                cancellation_effective_at=None,
            ),
            user_id="owner",
            db=self.db,
        )

        self.assertEqual(updated["status"], "active")
        self.assertIsNone(updated["paused_until"])
        self.assertIsNone(updated["recurrence_end_at"])
        self.assertIsNone(updated["cancellation_effective_at"])

    def test_create_response_contains_flexible_backend_equivalents_immediately(self):
        payload = create_subscription(
            SubscriptionCreate(
                name="Immediate quarterly", category=Category.software,
                amount=120, currency="AUD", interval_unit="month",
                interval_count=3,
            ),
            user_id="owner",
            db=self.db,
        )

        self.assertEqual(payload["cadence_label"], "Every 3 months")
        self.assertEqual(payload["monthly_equivalent"], 40)
        self.assertEqual(payload["yearly_equivalent"], 480)

    def test_payload_projects_stale_anchor_for_next_expected_charge(self):
        sub = self.create(
            interval_unit="month",
            interval_count=1,
            next_due=datetime(2026, 6, 30, 12),
        )
        with patch(
            "app.routers.subscriptions.utcnow",
            return_value=datetime(2026, 8, 5, 12),
        ):
            payload = subscription_payload(sub)

        self.assertEqual(payload["next_due"], "2026-06-30T12:00:00")
        self.assertEqual(payload["next_expected_at"], "2026-08-31T12:00:00")
        self.assertEqual(
            payload["next_expected_source"],
            "projected_from_recorded_cycle",
        )

    def test_equivalence_preview_uses_the_authoritative_backend_formula(self):
        payload = preview_equivalents(
            EquivalencePreview(
                amount=120,
                interval_unit="month",
                interval_count=3,
            ),
            user_id="owner",
        )

        self.assertEqual(payload["cadence_label"], "Every 3 months")
        self.assertEqual(payload["monthly_equivalent"], 40)
        self.assertEqual(payload["yearly_equivalent"], 480)

    def test_payload_keeps_precision_until_the_ui_formats_money(self):
        sub = self.create(
            amount=10,
            interval_unit="week",
            interval_count=2,
        )
        payload = subscription_payload(sub)

        self.assertEqual(payload["yearly_equivalent"], 260)
        self.assertEqual(payload["monthly_equivalent"], 260 / 12)
        self.assertNotEqual(payload["monthly_equivalent"], 21.67)

    def test_default_listing_excludes_terminal_lifecycle_rows(self):
        self.create(name="Active")
        self.create(name="Cancelled", status="cancelled")
        self.create(
            name="Ended by date",
            # Naive UTC, matching how the column is stored and how
            # effective_status compares it. Local time here would flake daily:
            # east of UTC the local date runs ahead, so "yesterday" local can
            # still be today in UTC and the row would not read as ended.
            recurrence_end_at=datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(days=1),
            next_due=None,
        )

        active = get_subscriptions(user_id="owner", db=self.db)
        all_rows = get_subscriptions(
            include_inactive=True, user_id="owner", db=self.db,
        )

        self.assertEqual([row["name"] for row in active], ["Active"])
        self.assertEqual(len(all_rows), 3)

    def test_queries_remain_scoped_to_the_authenticated_user(self):
        self.create(name="Mine")
        private = Subscription(
            user_id="other", name="Private", category=Category.other,
            amount=999, currency="AUD", cycle=BillingCycle.monthly,
            interval_unit="month", interval_count=1, is_active=True,
        )
        self.db.add(private)
        self.db.commit()

        rows = get_subscriptions(user_id="owner", db=self.db)

        self.assertEqual([row["name"] for row in rows], ["Mine"])

    def test_client_cannot_override_server_owned_currency_conversion(self):
        self.db.add(ExchangeRateSnapshot(
            base_currency="AUD",
            rates={
                "USD": 0.65, "GBP": 0.49, "SGD": 0.86,
                "EUR": 0.57, "JPY": 96.4,
            },
            provider="frankfurter",
            provider_date="2026-08-05",
            fetched_at=datetime.now(),
        ))
        self.db.commit()

        sub = self.create(
            amount=65,
            currency="USD",
            exchange_rate=99,
            converted_amount=9_999,
        )

        self.assertEqual(sub.converted_amount, 100)
        self.assertAlmostEqual(sub.exchange_rate, 1 / 0.65, places=7)

    def test_missing_rate_is_stored_as_unconverted_not_one_to_one(self):
        sub = self.create(
            amount=65,
            currency="USD",
            exchange_rate=1,
            converted_amount=65,
        )

        self.assertIsNone(sub.converted_amount)
        self.assertIsNone(sub.exchange_rate)

    def test_currency_edit_records_each_side_in_its_own_currency(self):
        sub = self.create(amount=100, currency="AUD")
        self.db.query(SubscriptionChange).delete()
        self.db.commit()

        update_subscription(
            sub.id,
            SubscriptionUpdate(amount=65, currency="USD"),
            user_id="owner",
            db=self.db,
        )

        changes = (
            self.db.query(SubscriptionChange)
            .order_by(SubscriptionChange.changed_at, SubscriptionChange.id)
            .all()
        )
        self.assertEqual(len(changes), 2)
        by_kind = {row.kind.value: row for row in changes}
        self.assertEqual(by_kind["removed"].currency, "AUD")
        self.assertEqual(by_kind["added"].currency, "USD")
        self.assertEqual(by_kind["removed"].old_monthly, 100 / 3)
        self.assertIsNone(by_kind["removed"].new_monthly)
        self.assertIsNone(by_kind["added"].old_monthly)
        self.assertEqual(by_kind["added"].new_monthly, 65 / 3)

    def test_duplicate_model_result_is_bounded_and_cached_by_payment_snapshot(self):
        first = self.create(name="Service one")
        second = self.create(name="Service two")
        with patch(
            "app.gmail.analyzer.find_duplicates",
            return_value=[(0, 1, "Same recurring service")],
        ) as model:
            initial = get_duplicates(user_id="owner", db=self.db)
            cached = get_duplicates(user_id="owner", db=self.db)

        self.assertEqual(initial, cached)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(
            {initial[0]["keep"]["id"], initial[0]["merge"]["id"]},
            {str(first.id), str(second.id)},
        )

    def test_duplicate_model_failure_is_not_reported_as_no_duplicates(self):
        self.create(name="Service one")
        self.create(name="Service two")
        with patch(
            "app.gmail.analyzer.find_duplicates",
            side_effect=RuntimeError("Duplicate check temporarily unavailable."),
        ), self.assertRaises(HTTPException) as caught:
            get_duplicates(user_id="owner", db=self.db)

        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("temporarily unavailable", caught.exception.detail)

    def test_false_positive_duplicate_dismissal_is_durable_and_idempotent(self):
        first = self.create(name="Service one")
        second = self.create(name="Service two")
        with patch(
            "app.gmail.analyzer.find_duplicates",
            return_value=[(0, 1, "Same recurring service")],
        ) as model:
            self.assertEqual(len(get_duplicates(user_id="owner", db=self.db)), 1)
            created = dismiss_duplicate_suggestion(
                DismissDuplicateRequest(
                    subscription_id=first.id,
                    possible_duplicate_id=second.id,
                ),
                user_id="owner",
                db=self.db,
            )
            repeated = dismiss_duplicate_suggestion(
                DismissDuplicateRequest(
                    subscription_id=second.id,
                    possible_duplicate_id=first.id,
                ),
                user_id="owner",
                db=self.db,
            )
            filtered = get_duplicates(user_id="owner", db=self.db)

        self.assertFalse(created["already_dismissed"])
        self.assertTrue(repeated["already_dismissed"])
        self.assertEqual(filtered, [])
        self.assertEqual(self.db.query(DuplicateDismissal).count(), 1)
        # Filtering a dismissal reuses the bounded cached model result.
        self.assertEqual(model.call_count, 1)

    def test_duplicate_dismissal_cannot_reference_another_users_payment(self):
        mine = self.create(name="Mine")
        private = Subscription(
            user_id="other", name="Private", category=Category.other,
            amount=10, currency="AUD", cycle=BillingCycle.monthly,
            interval_unit="month", interval_count=1, is_active=True,
        )
        self.db.add(private)
        self.db.commit()

        with self.assertRaises(HTTPException) as caught:
            dismiss_duplicate_suggestion(
                DismissDuplicateRequest(
                    subscription_id=mine.id,
                    possible_duplicate_id=private.id,
                ),
                user_id="owner",
                db=self.db,
            )

        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(self.db.query(DuplicateDismissal).count(), 0)


if __name__ == "__main__":
    unittest.main()
