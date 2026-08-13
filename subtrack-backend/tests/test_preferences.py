import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.database import Base  # noqa: E402
from app.models import UserPreference  # noqa: E402
from app.routers.preferences import (  # noqa: E402
    PreferenceUpdate,
    get_preferences,
    update_preferences,
)


class PreferenceContractTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_income_can_be_cleared_without_affecting_another_user(self):
        self.db.add_all([
            UserPreference(user_id="owner", monthly_income=5000),
            UserPreference(user_id="other", monthly_income=9000),
        ])
        self.db.commit()

        result = update_preferences(
            PreferenceUpdate(monthly_income=None), user_id="owner", db=self.db,
        )

        self.assertIsNone(result["monthly_income"])
        self.assertEqual(get_preferences("other", self.db)["monthly_income"], 9000)

    def test_non_finite_negative_and_unknown_values_fail_validation(self):
        for payload in (
            {"monthly_income": float("nan")},
            {"monthly_income": float("inf")},
            {"monthly_income": -1},
            {"base_currency": "CAD"},
            {"unexpected": True},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                PreferenceUpdate.model_validate(payload)

    def test_base_currency_change_atomically_converts_saved_income(self):
        self.db.add(UserPreference(
            user_id="owner", base_currency="AUD", monthly_income=5000,
        ))
        self.db.commit()
        snapshot = {
            "base": "AUD", "rates": {"USD": 0.65}, "stale": False,
            "fetched_at": "2026-08-05T00:00:00",
        }

        with patch(
            "app.routers.preferences.get_cached_rate_snapshot",
            return_value=snapshot,
        ):
            result = update_preferences(
                PreferenceUpdate(base_currency="USD"),
                user_id="owner",
                db=self.db,
            )

        self.assertEqual(result["base_currency"], "USD")
        self.assertEqual(result["monthly_income"], 3250)
        self.assertTrue(result["income_converted"])

    def test_base_change_rolls_back_when_income_cannot_be_converted(self):
        self.db.add(UserPreference(
            user_id="owner", base_currency="AUD", monthly_income=5000,
        ))
        self.db.commit()

        with patch(
            "app.routers.preferences.get_cached_rate_snapshot",
            return_value=None,
        ), self.assertRaises(HTTPException) as caught:
            update_preferences(
                PreferenceUpdate(base_currency="USD"),
                user_id="owner",
                db=self.db,
            )

        self.assertEqual(caught.exception.status_code, 409)
        self.db.rollback()
        preference = self.db.get(UserPreference, "owner")
        self.assertEqual(preference.base_currency, "AUD")
        self.assertEqual(preference.monthly_income, 5000)


if __name__ == "__main__":
    unittest.main()
