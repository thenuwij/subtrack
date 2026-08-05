import hashlib
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.database import Base
from app.main import app as api_app
from app.models import (
    AgentAction,
    AgentMessage,
    AgentResearchCache,
    AgentThread,
    BillingCycle,
    Category,
    ChangeKind,
    DetectedSubscription,
    DetectionStatus,
    DuplicateDismissal,
    ExchangeRateSnapshot,
    GmailAccount,
    GmailOAuthState,
    PaymentReminder,
    Subscription,
    SubscriptionChange,
    UserPreference,
)
from app.routers import account, gmail
from app.services import gmail_access


class AccountPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.owner = self._seed_user("owner", "owner-token-secret")
        self.other = self._seed_user("other", "other-token-secret")
        self.db.add(
            ExchangeRateSnapshot(
                base_currency="AUD",
                rates={"AUD": 1.0, "USD": 0.65},
                provider="test-provider",
                provider_date="2026-08-05",
                fetched_at=datetime(2026, 8, 5, 12, tzinfo=timezone.utc),
            )
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _seed_user(self, user_id: str, token: str) -> dict[str, object]:
        now = datetime(2026, 8, 5, 12, tzinfo=timezone.utc)
        subscription = Subscription(
            id=uuid4(),
            user_id=user_id,
            name=f"{user_id} payment",
            category=Category.software,
            amount=120,
            cycle=BillingCycle.monthly,
            interval_unit="month",
            interval_count=3,
            currency="AUD",
            next_due=now + timedelta(days=10),
        )
        distinct_subscription = Subscription(
            id=uuid4(),
            user_id=user_id,
            name=f"{user_id} distinct payment",
            category=Category.software,
            amount=80,
            cycle=BillingCycle.monthly,
            interval_unit="month",
            interval_count=1,
            currency="AUD",
            next_due=now + timedelta(days=20),
        )
        duplicate_dismissal = DuplicateDismissal(
            id=uuid4(),
            user_id=user_id,
            subscription_a_id=min(subscription.id, distinct_subscription.id),
            subscription_b_id=max(subscription.id, distinct_subscription.id),
        )
        change = SubscriptionChange(
            id=uuid4(),
            user_id=user_id,
            subscription_id=subscription.id,
            name=subscription.name,
            kind=ChangeKind.added,
            old_monthly=None,
            new_monthly=40,
            currency="AUD",
            changed_at=now,
        )
        gmail = GmailAccount(
            user_id=user_id,
            email_address=f"{user_id}@example.com",
            refresh_token_encrypted=token,
            scan_status="done",
            scan_processed=2,
            scan_total=2,
            scan_partial=False,
        )
        oauth_state = GmailOAuthState(
            state_hash=hashlib.sha256(f"{user_id}-state".encode()).hexdigest(),
            user_id=user_id,
            code_verifier_encrypted=f"{user_id}-pkce-secret",
            expires_at=now + timedelta(minutes=10),
        )
        detection = DetectedSubscription(
            id=uuid4(),
            user_id=user_id,
            merchant=f"{user_id} detected",
            sender_domain=f"{user_id}.example",
            product_key="product",
            category=Category.software,
            cycle=BillingCycle.monthly,
            interval_unit="month",
            interval_count=1,
            cadence_confidence="high",
            due_date_confidence="medium",
            amount_type="fixed",
            amount=15,
            currency="AUD",
            status=DetectionStatus.pending,
        )
        preference = UserPreference(
            user_id=user_id,
            base_currency="AUD",
            monthly_income=5000,
            timezone="Australia/Sydney",
        )
        reminder = PaymentReminder(
            id=uuid4(),
            user_id=user_id,
            subscription_id=subscription.id,
            kind="renewal",
            days_before=7,
            note=f"{user_id} reminder",
        )
        thread = AgentThread(
            id=uuid4(), user_id=user_id, title=f"{user_id} thread",
        )
        message = AgentMessage(
            id=uuid4(),
            thread_id=thread.id,
            user_id=user_id,
            role="assistant",
            sequence=0,
            content=f"{user_id} private conversation",
            status="completed",
        )
        action = AgentAction(
            id=uuid4(),
            thread_id=thread.id,
            assistant_message_id=message.id,
            user_id=user_id,
            action_type="add_subscription",
            payload_json={"name": f"{user_id} proposed payment"},
            summary="Add payment",
            description="Add one payment",
            fingerprint=f"{user_id}-fingerprint",
            status="pending",
            expires_at=now + timedelta(hours=1),
        )
        research = AgentResearchCache(
            id=uuid4(),
            user_id=user_id,
            subscription_id=subscription.id,
            fingerprint=f"{user_id}-research",
            market="Australia",
            result_json={"summary": f"{user_id} private research"},
            expires_at=now + timedelta(hours=6),
        )
        self.db.add_all(
            [
                subscription,
                distinct_subscription,
                duplicate_dismissal,
                change,
                gmail,
                oauth_state,
                detection,
                preference,
                reminder,
                thread,
                message,
                action,
                research,
            ]
        )
        return {
            "subscription": subscription,
            "distinct_subscription": distinct_subscription,
            "duplicate_dismissal": duplicate_dismissal,
            "change": change,
            "gmail": gmail,
            "oauth_state": oauth_state,
            "detection": detection,
            "preference": preference,
            "reminder": reminder,
            "thread": thread,
            "message": message,
            "action": action,
            "research": research,
        }

    def test_export_is_complete_user_scoped_and_excludes_oauth_secrets(self):
        with patch.object(account, "SessionLocal", self.Session):
            raw = b"".join(account._stream_user_export("owner"))
        payload = json.loads(raw)

        self.assertEqual(payload["scope"], "subtrack_application_data")
        self.assertEqual(payload["identity"]["user_id"], "owner")
        self.assertEqual(
            set(payload["data"]),
            {resource.name for resource in account.EXPORT_RESOURCES},
        )
        self.assertEqual(len(payload["data"]["subscriptions"]), 2)
        self.assertEqual(
            {row["name"] for row in payload["data"]["subscriptions"]},
            {"owner payment", "owner distinct payment"},
        )
        self.assertEqual(len(payload["data"]["duplicate_dismissals"]), 1)
        self.assertEqual(
            payload["data"]["assistant_messages"][0]["content"],
            "owner private conversation",
        )

        exported_text = raw.decode("utf-8")
        self.assertNotIn("owner-token-secret", exported_text)
        self.assertNotIn("other-token-secret", exported_text)
        self.assertNotIn("owner-pkce-secret", exported_text)
        self.assertNotIn("other-pkce-secret", exported_text)
        self.assertNotIn("other private", exported_text)
        self.assertNotIn("refresh_token_encrypted", exported_text)
        self.assertNotIn("exchange_rate_snapshots", exported_text)

    def test_transactional_deletion_removes_only_callers_app_data(self):
        with patch.object(
            account,
            "revoke_encrypted_refresh_token",
            return_value=gmail_access.GmailRevocationStatus.revoked,
        ) as revoke:
            response = account.delete_app_data(
                account.DeleteAppDataRequest(
                    confirmation="DELETE MY SUBTRACK DATA"
                ),
                user_id="owner",
                db=self.db,
            )

        revoke.assert_called_once_with("owner-token-secret")
        self.assertTrue(response["deleted"])
        self.assertEqual(response["gmail_revocation"], "revoked")
        self.assertFalse(response["supabase_auth_identity_deleted"])
        self.assertEqual(response["deleted_records"]["subscriptions"], 2)
        self.assertEqual(response["deleted_records"]["duplicate_dismissals"], 1)
        self.assertTrue(all(
            count == 1
            for name, count in response["deleted_records"].items()
            if name not in {"subscriptions", "duplicate_dismissals"}
        ))

        for _, model in account.DELETE_ORDER:
            with self.subTest(model=model.__name__):
                self.assertEqual(
                    self.db.query(model).filter(model.user_id == "owner").count(), 0
                )
                self.assertEqual(
                    self.db.query(model).filter(model.user_id == "other").count(),
                    2 if model is Subscription else 1,
                )

        self.assertEqual(self.db.query(ExchangeRateSnapshot).count(), 1)
        self.assertEqual(
            self.db.get(ExchangeRateSnapshot, "AUD").provider,
            "test-provider",
        )

    def test_gmail_disconnect_revokes_and_removes_only_owned_connection_state(self):
        with patch.object(
            gmail,
            "revoke_encrypted_refresh_token",
            return_value=gmail_access.GmailRevocationStatus.failed,
        ) as revoke:
            response = gmail.gmail_disconnect(user_id="owner", db=self.db)

        revoke.assert_called_once_with("owner-token-secret")
        self.assertEqual(response["gmail_revocation"], "failed")
        self.assertIsNone(self.db.get(GmailAccount, "owner"))
        self.assertEqual(
            self.db.query(GmailOAuthState).filter(
                GmailOAuthState.user_id == "owner"
            ).count(),
            0,
        )
        self.assertIsNotNone(self.db.get(GmailAccount, "other"))
        self.assertEqual(
            self.db.query(GmailOAuthState).filter(
                GmailOAuthState.user_id == "other"
            ).count(),
            1,
        )
        # Disconnecting access does not silently erase reviewed finance data.
        self.assertEqual(
            self.db.query(Subscription).filter(Subscription.user_id == "owner").count(),
            2,
        )

    def test_gmail_disconnect_rolls_back_without_logging_database_details(self):
        with (
            patch.object(
                gmail,
                "revoke_encrypted_refresh_token",
            ) as revoke,
            patch.object(
                self.db,
                "commit",
                side_effect=RuntimeError("private database statement"),
            ),
            self.assertRaises(HTTPException) as caught,
            self.assertLogs("app.routers.gmail", level="ERROR") as logs,
        ):
            gmail.gmail_disconnect(user_id="owner", db=self.db)

        self.assertEqual(caught.exception.status_code, 500)
        self.assertNotIn("private database statement", "\n".join(logs.output))
        revoke.assert_not_called()
        self.assertIsNotNone(self.db.get(GmailAccount, "owner"))
        self.assertEqual(
            self.db.query(GmailOAuthState).filter(
                GmailOAuthState.user_id == "owner"
            ).count(),
            1,
        )

    def test_deletion_rolls_back_every_table_when_any_step_fails(self):
        def fail_after_first_delete(db, user_id):
            db.execute(delete(AgentAction).where(AgentAction.user_id == user_id))
            raise RuntimeError("simulated database failure")

        with (
            patch.object(
                account,
                "revoke_encrypted_refresh_token",
                return_value=gmail_access.GmailRevocationStatus.failed,
            ),
            patch.object(account, "_delete_owned_rows", side_effect=fail_after_first_delete),
            self.assertRaises(HTTPException) as caught,
            self.assertLogs("app.routers.account", level="ERROR") as logs,
        ):
            account.delete_app_data(
                account.DeleteAppDataRequest(
                    confirmation="DELETE MY SUBTRACK DATA"
                ),
                user_id="owner",
                db=self.db,
            )

        self.assertEqual(caught.exception.status_code, 500)
        self.assertNotIn("simulated database failure", "\n".join(logs.output))
        self.assertEqual(
            self.db.query(AgentAction).filter(AgentAction.user_id == "owner").count(),
            1,
        )
        self.assertEqual(
            self.db.query(Subscription).filter(Subscription.user_id == "owner").count(),
            2,
        )

    def test_every_user_owned_model_is_explicitly_deleted_and_export_policy_is_explicit(self):
        owned_models = {
            mapper.class_
            for mapper in Base.registry.mappers
            if "user_id" in mapper.local_table.c
        }
        deleted_models = {model for _, model in account.DELETE_ORDER}
        exported_models = {resource.model for resource in account.EXPORT_RESOURCES}

        self.assertEqual(deleted_models, owned_models)
        self.assertEqual(exported_models, owned_models - {GmailOAuthState})

    def test_export_and_deletion_contracts_require_bearer_auth(self):
        paths = api_app.openapi()["paths"]

        self.assertEqual(
            paths["/account/export"]["get"]["security"],
            [{"HTTPBearer": []}],
        )
        self.assertEqual(
            paths["/account/data"]["delete"]["security"],
            [{"HTTPBearer": []}],
        )
        self.assertTrue(
            paths["/account/data"]["delete"]["requestBody"]["required"]
        )


class GmailRevocationTests(unittest.TestCase):
    def test_revoke_posts_only_to_google_and_never_requires_client_credentials(self):
        response = type("Response", (), {"status_code": 200})()
        with (
            patch.object(gmail_access, "decrypt_token", return_value="clear-secret"),
            patch.object(gmail_access.httpx, "post", return_value=response) as post,
        ):
            status = gmail_access.revoke_encrypted_refresh_token("encrypted")

        self.assertEqual(status, gmail_access.GmailRevocationStatus.revoked)
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args, (gmail_access.GOOGLE_REVOCATION_URL,))
        self.assertEqual(kwargs["data"], {"token": "clear-secret"})

    def test_revocation_failure_is_bounded_and_does_not_block_local_deletion(self):
        with (
            patch.object(gmail_access, "decrypt_token", return_value="clear-secret"),
            patch.object(
                gmail_access.httpx,
                "post",
                side_effect=gmail_access.httpx.TimeoutException("timeout"),
            ),
            self.assertLogs("app.services.gmail_access", level="WARNING"),
        ):
            status = gmail_access.revoke_encrypted_refresh_token("encrypted")

        self.assertEqual(status, gmail_access.GmailRevocationStatus.failed)
        self.assertEqual(
            gmail_access.revoke_encrypted_refresh_token(None),
            gmail_access.GmailRevocationStatus.not_connected,
        )


if __name__ == "__main__":
    unittest.main()
