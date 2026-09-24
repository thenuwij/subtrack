import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402
from app.middleware import auth  # noqa: E402
from app.models import (  # noqa: E402
    AgentMessage,
    AgentThread,
    DemoSession,
    DetectedSubscription,
    PaymentReminder,
    Subscription,
    SubscriptionChange,
    UserPreference,
)
from app.routers.account import DeleteAppDataRequest, delete_app_data  # noqa: E402
from app.routers.agent import _enforce_agent_rate_limit  # noqa: E402
from app.routers.demo import create_demo_session  # noqa: E402
from app.routers.gmail import gmail_connect, start_scan  # noqa: E402

DEMO_SECRET = "demo-secret-" + "x" * 60


def credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def request_from(address: str):
    return SimpleNamespace(
        headers={"x-forwarded-for": f"203.0.113.9, {address}"},
        client=SimpleNamespace(host="10.0.0.1"),
    )


class DemoTokenTests(unittest.TestCase):
    def test_demo_token_round_trips_to_its_demo_user(self):
        with patch.object(settings, "demo_token_secret", DEMO_SECRET):
            token = auth.issue_demo_token(
                "demo_abc", datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
            )
            self.assertEqual(auth.verify_token(credentials(token)), "demo_abc")

    def test_demo_tokens_are_rejected_when_the_demo_is_disabled(self):
        with patch.object(settings, "demo_token_secret", DEMO_SECRET):
            token = auth.issue_demo_token(
                "demo_abc", datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
            )
        with patch.object(settings, "demo_token_secret", ""):
            with self.assertRaises(HTTPException) as caught:
                auth.verify_token(credentials(token))
        self.assertEqual(caught.exception.status_code, 401)

    def test_demo_secret_cannot_mint_a_real_user_token(self):
        forged = jwt.encode(
            {
                "sub": "real-user-uuid",
                "aud": auth.DEMO_TOKEN_AUDIENCE,
                "iss": auth.DEMO_TOKEN_AUDIENCE,
                "exp": int(time.time()) + 300,
            },
            DEMO_SECRET,
            algorithm=auth.DEMO_TOKEN_ALGORITHM,
        )
        with patch.object(settings, "demo_token_secret", DEMO_SECRET):
            with self.assertRaises(HTTPException) as caught:
                auth.verify_token(credentials(forged))
        self.assertEqual(caught.exception.status_code, 401)

    def test_supabase_secret_cannot_sign_a_demo_token(self):
        forged = jwt.encode(
            {
                "sub": "demo_abc",
                "aud": auth.DEMO_TOKEN_AUDIENCE,
                "iss": auth.DEMO_TOKEN_AUDIENCE,
                "exp": int(time.time()) + 300,
            },
            "other-secret-" + "y" * 60,
            algorithm=auth.DEMO_TOKEN_ALGORITHM,
        )
        with patch.object(settings, "demo_token_secret", DEMO_SECRET):
            with self.assertRaises(HTTPException):
                auth.verify_token(credentials(forged))

    def test_expired_demo_token_is_rejected(self):
        with patch.object(settings, "demo_token_secret", DEMO_SECRET):
            token = auth.issue_demo_token(
                "demo_abc", datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5),
            )
            with self.assertRaises(HTTPException):
                auth.verify_token(credentials(token))


class DemoSessionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_session_is_created_with_a_usable_demo_token(self):
        with patch.object(settings, "demo_token_secret", DEMO_SECRET):
            result = create_demo_session(request_from("198.51.100.1"), self.db)
            user_id = auth.verify_token(credentials(result["access_token"]))

        self.assertTrue(user_id.startswith("demo_"))
        row = self.db.query(DemoSession).one()
        self.assertEqual(row.demo_user_id, user_id)
        self.assertNotIn("198.51.100.1", row.client_hash)

    def test_disabled_demo_returns_not_found(self):
        with patch.object(settings, "demo_token_secret", ""):
            with self.assertRaises(HTTPException) as caught:
                create_demo_session(request_from("198.51.100.1"), self.db)
        self.assertEqual(caught.exception.status_code, 404)

    def test_each_visitor_is_limited_per_hour(self):
        with (
            patch.object(settings, "demo_token_secret", DEMO_SECRET),
            patch.object(settings, "demo_sessions_per_client_per_hour", 2),
        ):
            create_demo_session(request_from("198.51.100.1"), self.db)
            create_demo_session(request_from("198.51.100.1"), self.db)
            with self.assertRaises(HTTPException) as caught:
                create_demo_session(request_from("198.51.100.1"), self.db)
            create_demo_session(request_from("198.51.100.2"), self.db)
        self.assertEqual(caught.exception.status_code, 429)

    def test_total_demo_sessions_are_limited_per_hour(self):
        with (
            patch.object(settings, "demo_token_secret", DEMO_SECRET),
            patch.object(settings, "demo_sessions_per_hour", 2),
        ):
            create_demo_session(request_from("198.51.100.1"), self.db)
            create_demo_session(request_from("198.51.100.2"), self.db)
            with self.assertRaises(HTTPException) as caught:
                create_demo_session(request_from("198.51.100.3"), self.db)
        self.assertEqual(caught.exception.status_code, 429)

    def test_new_demo_is_seeded_with_realistic_data(self):
        with patch.object(settings, "demo_token_secret", DEMO_SECRET):
            result = create_demo_session(request_from("198.51.100.1"), self.db)
            user_id = auth.verify_token(credentials(result["access_token"]))

        subs = self.db.query(Subscription).filter(Subscription.user_id == user_id).all()
        names = {sub.name for sub in subs}
        self.assertEqual(len(subs), 13)
        self.assertIn("Spotify Premium", names)
        self.assertNotIn("Kayo Sports", names)
        self.assertEqual(
            next(sub for sub in subs if sub.name == "Aussie Broadband").amount, 89,
        )
        kinds = sorted(
            change.kind.value
            for change in self.db.query(SubscriptionChange).filter(
                SubscriptionChange.user_id == user_id,
            )
        )
        self.assertEqual(kinds, ["added", "price_change", "removed"])
        self.assertEqual(
            self.db.query(DetectedSubscription).filter(
                DetectedSubscription.user_id == user_id,
            ).count(),
            3,
        )
        reminder_kinds = {
            reminder.kind for reminder in self.db.query(PaymentReminder).filter(
                PaymentReminder.user_id == user_id,
            )
        }
        self.assertEqual(reminder_kinds, {"renewal", "trial_end"})
        preference = self.db.get(UserPreference, user_id)
        self.assertIsNone(preference.onboarding_completed_at)
        self.assertEqual(preference.monthly_income, 6500)

    def test_new_demo_uses_few_database_round_trips(self):
        statements = []
        event.listen(
            self.engine, "before_cursor_execute",
            lambda *args, **kwargs: statements.append(1),
        )
        with patch.object(settings, "demo_token_secret", DEMO_SECRET):
            create_demo_session(request_from("198.51.100.1"), self.db)
        self.assertLessEqual(len(statements), 15)

    def test_expired_demos_are_purged_when_a_new_demo_starts(self):
        with patch.object(settings, "demo_token_secret", DEMO_SECRET):
            first = create_demo_session(request_from("198.51.100.1"), self.db)
            old_user = auth.verify_token(credentials(first["access_token"]))
            self.db.query(DemoSession).filter(
                DemoSession.demo_user_id == old_user,
            ).update({"expires_at": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)})
            self.db.commit()
            create_demo_session(request_from("198.51.100.2"), self.db)

        self.assertIsNone(self.db.get(DemoSession, old_user))
        for model in (Subscription, SubscriptionChange, DetectedSubscription, PaymentReminder):
            self.assertEqual(
                self.db.query(model).filter(model.user_id == old_user).count(), 0,
            )
        self.assertIsNone(self.db.get(UserPreference, old_user))
        self.assertEqual(self.db.query(DemoSession).count(), 1)

    def test_expired_demos_are_purged_when_the_api_starts(self):
        from app.main import _purge_expired_demos_at_startup

        with patch.object(settings, "demo_token_secret", DEMO_SECRET):
            session = create_demo_session(request_from("198.51.100.3"), self.db)
            demo_user = auth.verify_token(credentials(session["access_token"]))
        self.db.query(DemoSession).filter(
            DemoSession.demo_user_id == demo_user,
        ).update({"expires_at": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)})
        self.db.commit()

        with patch("app.database.SessionLocal", sessionmaker(bind=self.db.get_bind())):
            _purge_expired_demos_at_startup()

        self.db.expire_all()
        self.assertIsNone(self.db.get(DemoSession, demo_user))
        self.assertEqual(self.db.query(Subscription).filter(Subscription.user_id == demo_user).count(), 0)


class DemoGuardrailTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_demo_users_cannot_connect_or_scan_gmail(self):
        for handler in (gmail_connect, start_scan):
            with self.assertRaises(HTTPException) as caught:
                handler(user_id="demo_abc", db=self.db)
            self.assertEqual(caught.exception.status_code, 403)
            self.assertIn("demo", caught.exception.detail)

    def test_demo_users_cannot_delete_account_data(self):
        with self.assertRaises(HTTPException) as caught:
            delete_app_data(
                DeleteAppDataRequest(confirmation="DELETE MY SUBTRACK DATA"),
                user_id="demo_abc",
                db=self.db,
            )
        self.assertEqual(caught.exception.status_code, 403)

    def _add_assistant_messages(self, user_id: str, count: int):
        thread = AgentThread(user_id=user_id, title="Demo", next_message_sequence=count)
        self.db.add(thread)
        self.db.flush()
        hour_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        self.db.add_all([
            AgentMessage(
                thread_id=thread.id, user_id=user_id, role="assistant",
                sequence=index, content="Reply", created_at=hour_ago,
            )
            for index in range(count)
        ])
        self.db.commit()

    def test_demo_assistant_use_is_capped_for_the_whole_session(self):
        with patch.object(settings, "demo_agent_messages", 5):
            self._add_assistant_messages("demo_abc", 4)
            _enforce_agent_rate_limit(self.db, "demo_abc")
            self._add_assistant_messages("demo_abc", 1)
            with self.assertRaises(HTTPException) as caught:
                _enforce_agent_rate_limit(self.db, "demo_abc")
        self.assertEqual(caught.exception.status_code, 429)
        self.assertIn("demo", caught.exception.detail)

    def test_real_users_are_not_subject_to_the_demo_cap(self):
        with patch.object(settings, "demo_agent_messages", 5):
            self._add_assistant_messages("real-user", 8)
            _enforce_agent_rate_limit(self.db, "real-user")


if __name__ == "__main__":
    unittest.main()
