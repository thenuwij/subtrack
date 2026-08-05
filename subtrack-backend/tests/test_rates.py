import os
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.database import Base
from app.models import ExchangeRateSnapshot
from app.routers import rates as rates_router


def complete_rates(base: str = "AUD", *, usd: float = 0.65) -> dict[str, float]:
    values = {
        "AUD": 1.52,
        "USD": usd,
        "GBP": 0.49,
        "SGD": 0.86,
        "EUR": 0.57,
        "JPY": 96.4,
    }
    values.pop(base)
    return values


class SharedRateCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        with rates_router._cache_lock:
            rates_router._cache.clear()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        with rates_router._cache_lock:
            rates_router._cache.clear()

    def seed_snapshot(self, *, age: timedelta, usd: float = 0.65):
        fetched_at = rates_router._utcnow() - age
        self.db.add(
            ExchangeRateSnapshot(
                base_currency="AUD",
                rates=complete_rates(usd=usd),
                provider="frankfurter",
                provider_date="2026-08-04",
                fetched_at=fetched_at,
            )
        )
        self.db.commit()
        return fetched_at

    async def test_fresh_persisted_snapshot_hydrates_restart_without_provider_call(
        self,
    ):
        fetched_at = self.seed_snapshot(age=timedelta(minutes=10))
        provider = AsyncMock()

        with patch.object(rates_router, "_fetch_provider_snapshot", provider):
            response = await rates_router.get_rates("AUD", "user", self.db)

        provider.assert_not_awaited()
        self.assertTrue(response["cached"])
        self.assertFalse(response["stale"])
        self.assertEqual(response["cache_source"], "persistent_cache")
        self.assertEqual(response["fetched_at"], fetched_at.isoformat())
        self.assertEqual(response["rates"]["USD"], 0.65)

    async def test_provider_failure_uses_persisted_stale_snapshot_honestly(self):
        self.seed_snapshot(age=timedelta(hours=2), usd=0.65)
        provider = AsyncMock(side_effect=RuntimeError("provider unavailable"))

        with (
            patch.object(rates_router, "_fetch_provider_snapshot", provider),
            self.assertLogs("app.routers.rates", level="WARNING"),
        ):
            response = await rates_router.get_rates("AUD", "user", self.db)

        provider.assert_awaited_once_with("AUD")
        self.assertTrue(response["cached"])
        self.assertTrue(response["stale"])
        self.assertEqual(response["fallback_reason"], "provider_unavailable")
        self.assertEqual(response["cache_source"], "persistent_cache")
        self.assertNotIn("AUD", response["rates"])
        self.assertEqual(response["rates"]["USD"], 0.65)

    async def test_provider_success_is_persisted_and_survives_memory_clear(self):
        provider_rates = complete_rates(usd=0.7)
        provider = AsyncMock(return_value=(provider_rates, "2026-08-05"))

        with patch.object(rates_router, "_fetch_provider_snapshot", provider):
            response = await rates_router.get_rates("AUD", "user", self.db)

        self.assertFalse(response["cached"])
        self.assertFalse(response["stale"])
        row = self.db.get(ExchangeRateSnapshot, "AUD")
        self.assertIsNotNone(row)
        self.assertEqual(row.rates, provider_rates)
        self.assertEqual(row.provider_date, "2026-08-05")

        with rates_router._cache_lock:
            rates_router._cache.clear()
        restored = rates_router.get_cached_rate_snapshot("AUD", db=self.db)
        self.assertIsNotNone(restored)
        self.assertEqual(restored["rates"]["USD"], 0.7)
        self.assertEqual(restored["cache_source"], "persistent_cache")

    async def test_no_snapshot_and_provider_failure_returns_503_not_one_to_one(self):
        provider = AsyncMock(side_effect=RuntimeError("provider unavailable"))
        with (
            patch.object(rates_router, "_fetch_provider_snapshot", provider),
            self.assertLogs("app.routers.rates", level="WARNING"),
            self.assertRaises(HTTPException) as caught,
        ):
            await rates_router.get_rates("AUD", "user", self.db)

        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(
            caught.exception.detail,
            "Exchange rate service unavailable and no cached rates exist.",
        )

    async def test_unsupported_base_is_rejected_before_provider_access(self):
        provider = AsyncMock()
        with (
            patch.object(rates_router, "_fetch_provider_snapshot", provider),
            self.assertRaises(HTTPException) as caught,
        ):
            await rates_router.get_rates("CAD", "user", self.db)
        self.assertEqual(caught.exception.status_code, 400)
        provider.assert_not_awaited()

    async def test_missing_cache_table_during_rolling_deploy_still_returns_live_rates(
        self,
    ):
        ExchangeRateSnapshot.__table__.drop(self.engine)
        provider_rates = complete_rates(usd=0.72)
        provider = AsyncMock(return_value=(provider_rates, "2026-08-05"))

        with (
            patch.object(rates_router, "_fetch_provider_snapshot", provider),
            self.assertLogs("app.routers.rates", level="ERROR"),
        ):
            response = await rates_router.get_rates("AUD", "user", self.db)

        self.assertFalse(response["cached"])
        self.assertEqual(response["rates"]["USD"], 0.72)
        self.assertEqual(self.db.execute(text("SELECT 1")).scalar_one(), 1)

    def test_provider_rate_map_is_complete_valid_and_bounded(self):
        raw = {**complete_rates(), "CAD": 123.0}
        validated = rates_router._validate_rates(raw, "AUD")
        self.assertEqual(set(validated), rates_router.SUPPORTED_CURRENCIES - {"AUD"})
        self.assertNotIn("CAD", validated)

        for invalid in (
            {key: value for key, value in raw.items() if key != "USD"},
            {**raw, "USD": float("nan")},
            {**raw, "USD": True},
        ):
            with (
                self.subTest(invalid=invalid),
                self.assertRaises((TypeError, ValueError)),
            ):
                rates_router._validate_rates(invalid, "AUD")

    def test_fresh_memory_snapshot_remains_the_zero_query_fast_path(self):
        rates_router._store_memory_entry(
            "AUD",
            {
                "rates": complete_rates(),
                "fetched_at": rates_router._utcnow(),
                "provider": "frankfurter",
                "provider_date": "2026-08-05",
                "cache_source": "provider",
            },
        )
        with patch.object(rates_router, "_load_persisted_entry") as load_persisted:
            snapshot = rates_router.get_cached_rate_snapshot("AUD", db=self.db)
        load_persisted.assert_not_called()
        self.assertFalse(snapshot["stale"])
        self.assertEqual(snapshot["rates"]["USD"], 0.65)

    def test_persistent_upsert_keeps_one_newest_row_per_base(self):
        first = rates_router._utcnow() - timedelta(minutes=5)
        second = rates_router._utcnow()
        rates_router._persist_snapshot(
            self.db,
            base="AUD",
            rates=complete_rates(usd=0.65),
            fetched_at=first,
            provider_date="2026-08-04",
        )
        rates_router._persist_snapshot(
            self.db,
            base="AUD",
            rates=complete_rates(usd=0.71),
            fetched_at=second,
            provider_date="2026-08-05",
        )

        self.assertEqual(self.db.query(ExchangeRateSnapshot).count(), 1)
        row = self.db.get(ExchangeRateSnapshot, "AUD")
        self.assertEqual(row.rates["USD"], 0.71)
        self.assertEqual(row.fetched_at, second)

    def test_corrupt_persisted_snapshot_is_never_used(self):
        self.db.add(
            ExchangeRateSnapshot(
                base_currency="AUD",
                rates={"USD": 1.0},
                provider="frankfurter",
                provider_date="not-a-date",
                fetched_at=rates_router._utcnow(),
            )
        )
        self.db.commit()
        with self.assertLogs("app.routers.rates", level="ERROR"):
            snapshot = rates_router.get_cached_rate_snapshot("AUD", db=self.db)
        self.assertIsNone(snapshot)

    def test_storage_conversion_never_invents_cross_currency_parity(self):
        converted, rate, quality = rates_router.conversion_for_storage(
            25, "CAD", "AUD", self.db,
        )
        self.assertIsNone(converted)
        self.assertIsNone(rate)
        self.assertEqual(quality, "unsupported_currency")

        converted, rate, quality = rates_router.conversion_for_storage(
            25, "USD", "AUD", self.db,
        )
        self.assertIsNone(converted)
        self.assertIsNone(rate)
        self.assertEqual(quality, "unconverted")


if __name__ == "__main__":
    unittest.main()
