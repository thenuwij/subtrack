import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402
from app.middleware import auth  # noqa: E402
from app.models import DemoSession  # noqa: E402
from app.routers.demo import create_demo_session  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
