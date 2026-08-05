import base64
import hashlib
import os
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402
from app.gmail.crypto import decrypt_token  # noqa: E402
from app.models import GmailAccount, GmailOAuthState  # noqa: E402
from app.routers import gmail  # noqa: E402


TEST_FERNET_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


class FakeFlow:
    def __init__(self, credentials=None, error: Exception | None = None):
        self.credentials = credentials
        self.error = error
        self.codes: list[str] = []

    def fetch_token(self, *, code: str, **_kwargs):
        self.codes.append(code)
        if self.error:
            raise self.error


class GmailOAuthSecurityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.setting_patches = (
            patch.object(settings, "google_client_id", "client.example.apps.googleusercontent.com"),
            patch.object(settings, "google_client_secret", "google-secret"),
            patch.object(settings, "google_redirect_uri", "https://api.example/gmail/callback"),
            patch.object(settings, "frontend_url", "https://app.example"),
            patch.object(settings, "token_encryption_key", TEST_FERNET_KEY),
        )
        for setting_patch in self.setting_patches:
            setting_patch.start()

    def tearDown(self):
        for setting_patch in reversed(self.setting_patches):
            setting_patch.stop()
        self.db.close()
        self.engine.dispose()

    def start(self, user_id: str = "owner") -> tuple[str, str]:
        result = gmail.gmail_connect(user_id=user_id, db=self.db)
        parsed = urlparse(result["auth_url"])
        params = parse_qs(parsed.query)
        return result["auth_url"], params["state"][0]

    @staticmethod
    def credentials(**changes):
        values = {
            "granted_scopes": list(gmail.SCOPES),
            "scopes": list(gmail.SCOPES),
            "refresh_token": "refresh-token",
            "id_token": "signed-google-id-token",
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def complete(self, state: str, *, user_id: str = "owner", flow=None):
        flow = flow or FakeFlow(self.credentials())
        with (
            patch.object(gmail, "_build_flow", return_value=flow) as build_flow,
            patch.object(gmail, "_verify_google_identity", return_value="owner@gmail.com"),
        ):
            result = gmail.gmail_oauth_complete(
                gmail.GmailOAuthComplete(code="google-code", state=state),
                user_id=user_id,
                db=self.db,
            )
        return result, flow, build_flow

    def test_connect_persists_only_hashed_state_and_encrypted_pkce_verifier(self):
        auth_url, state = self.start()
        params = parse_qs(urlparse(auth_url).query)
        row = self.db.get(GmailOAuthState, hashlib.sha256(state.encode()).hexdigest())

        self.assertIsNotNone(row)
        self.assertNotEqual(row.state_hash, state)
        self.assertNotIn(state, row.code_verifier_encrypted)
        verifier = decrypt_token(row.code_verifier_encrypted)
        expected_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest(),
        ).decode().rstrip("=")
        self.assertGreaterEqual(len(verifier), 43)
        self.assertLessEqual(len(verifier), 128)
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertEqual(params["code_challenge"], [expected_challenge])

    def test_public_callback_only_redirects_and_never_attaches_mailbox(self):
        _, state = self.start()

        response = gmail.gmail_callback(code="google-code", state=state)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        location = urlparse(response.headers["location"])
        self.assertEqual(
            f"{location.scheme}://{location.netloc}{location.path}",
            "https://app.example/auth/gmail/callback",
        )
        self.assertEqual(location.query, "")
        self.assertEqual(parse_qs(location.fragment), {
            "code": ["google-code"],
            "state": [state],
        })
        self.assertEqual(self.db.query(GmailAccount).count(), 0)
        self.assertEqual(self.db.query(GmailOAuthState).count(), 1)

    def test_authenticated_completion_uses_stored_verifier_and_saves_account(self):
        _, state = self.start()
        row = self.db.get(GmailOAuthState, hashlib.sha256(state.encode()).hexdigest())
        verifier = decrypt_token(row.code_verifier_encrypted)

        result, flow, build_flow = self.complete(state)

        self.assertEqual(result, {
            "connected": True,
            "email_address": "owner@gmail.com",
        })
        build_flow.assert_called_once_with(state=state, code_verifier=verifier)
        self.assertEqual(flow.codes, ["google-code"])
        self.assertEqual(self.db.query(GmailOAuthState).count(), 0)
        account = self.db.get(GmailAccount, "owner")
        self.assertEqual(account.email_address, "owner@gmail.com")
        self.assertEqual(decrypt_token(account.refresh_token_encrypted), "refresh-token")

    def test_state_cannot_be_completed_by_a_different_signed_in_user(self):
        _, state = self.start("owner")

        with self.assertRaises(HTTPException) as caught:
            self.complete(state, user_id="attacker")

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(self.db.query(GmailOAuthState).count(), 1)
        self.assertEqual(self.db.query(GmailAccount).count(), 0)

    def test_expired_state_is_consumed_without_calling_google(self):
        _, state = self.start()
        row = self.db.get(GmailOAuthState, hashlib.sha256(state.encode()).hexdigest())
        row.expires_at = gmail._utcnow() - timedelta(seconds=1)
        self.db.commit()

        with (
            patch.object(gmail, "_build_flow") as build_flow,
            self.assertRaises(HTTPException) as caught,
        ):
            gmail.gmail_oauth_complete(
                gmail.GmailOAuthComplete(code="google-code", state=state),
                user_id="owner",
                db=self.db,
            )

        self.assertEqual(caught.exception.status_code, 400)
        build_flow.assert_not_called()
        self.assertEqual(self.db.query(GmailOAuthState).count(), 0)

    def test_successful_state_is_one_time_and_replay_cannot_exchange(self):
        _, state = self.start()
        self.complete(state)

        with (
            patch.object(gmail, "_build_flow") as replay_flow,
            self.assertRaises(HTTPException) as caught,
        ):
            gmail.gmail_oauth_complete(
                gmail.GmailOAuthComplete(code="second-code", state=state),
                user_id="owner",
                db=self.db,
            )

        self.assertEqual(caught.exception.status_code, 400)
        replay_flow.assert_not_called()

    def test_failed_exchange_still_consumes_state_and_does_not_log_secrets(self):
        _, state = self.start()
        flow = FakeFlow(error=RuntimeError("google-code state=" + state))

        with (
            patch.object(gmail, "_build_flow", return_value=flow),
            self.assertLogs("app.routers.gmail", level="WARNING") as logs,
            self.assertRaises(HTTPException),
        ):
            gmail.gmail_oauth_complete(
                gmail.GmailOAuthComplete(code="google-code", state=state),
                user_id="owner",
                db=self.db,
            )

        rendered_logs = " ".join(logs.output)
        self.assertNotIn("google-code", rendered_logs)
        self.assertNotIn(state, rendered_logs)
        self.assertEqual(self.db.query(GmailOAuthState).count(), 0)
        self.assertEqual(self.db.query(GmailAccount).count(), 0)

    def test_missing_scope_or_refresh_token_fails_closed_after_consumption(self):
        cases = (
            self.credentials(granted_scopes=["openid"]),
            self.credentials(refresh_token=None),
        )
        for index, credentials in enumerate(cases):
            with self.subTest(index=index):
                _, state = self.start()
                flow = FakeFlow(credentials)
                with (
                    patch.object(gmail, "_build_flow", return_value=flow),
                    self.assertRaises(HTTPException) as caught,
                ):
                    gmail.gmail_oauth_complete(
                        gmail.GmailOAuthComplete(code="google-code", state=state),
                        user_id="owner",
                        db=self.db,
                    )
                self.assertEqual(caught.exception.status_code, 422)
                self.assertEqual(self.db.query(GmailOAuthState).count(), 0)
                self.assertEqual(self.db.query(GmailAccount).count(), 0)

    def test_google_identity_requires_verified_email_and_configured_audience(self):
        claims = {
            "iss": "https://accounts.google.com",
            "sub": "google-subject",
            "email": "owner@gmail.com",
            "email_verified": True,
        }
        with patch.object(
            gmail.google_id_token,
            "verify_oauth2_token",
            return_value=claims,
        ) as verify:
            self.assertEqual(
                gmail._verify_google_identity("signed-id-token"),
                "owner@gmail.com",
            )
        self.assertEqual(verify.call_args.args[2], settings.google_client_id)
        self.assertEqual(verify.call_args.kwargs["clock_skew_in_seconds"], 30)

        claims["email_verified"] = False
        with (
            patch.object(
                gmail.google_id_token,
                "verify_oauth2_token",
                return_value=claims,
            ),
            self.assertRaises(gmail.GmailIdentityError),
        ):
            gmail._verify_google_identity("signed-id-token")

    def test_legacy_signed_state_is_not_accepted_by_new_callback_contract(self):
        response = gmail.gmail_callback(
            code="google-code",
            state="legacy.jwt.state",
        )
        location = urlparse(response.headers["location"])
        self.assertEqual(location.query, "")
        params = parse_qs(location.fragment)
        self.assertEqual(params, {"error": ["invalid_oauth_response"]})


if __name__ == "__main__":
    unittest.main()


class GmailScopeReportingTests(GmailOAuthSecurityTests):
    """Google reports granted scopes inconsistently; only a real refusal counts.

    Read access to Gmail is a Google "restricted" scope, so consent renders it
    as its own tickbox that starts unticked. Continuing past it returns a
    perfectly valid token that cannot read mail, which is the most common way
    a first connection attempt fails — so this check has to be exact in both
    directions: never accept a genuine refusal, never invent one.
    """

    def _expect_refusal(self, credentials):
        _, state = self.start()
        with (
            patch.object(gmail, "_build_flow", return_value=FakeFlow(credentials)),
            self.assertRaises(HTTPException) as caught,
        ):
            gmail.gmail_oauth_complete(
                gmail.GmailOAuthComplete(code="google-code", state=state),
                user_id="owner",
                db=self.db,
            )
        return caught.exception

    def test_an_omitted_scope_means_the_requested_set_was_granted(self):
        # Per OAuth, no `scope` in the token response means "as requested".
        result, _, _ = self.complete(
            self.start()[1],
            flow=FakeFlow(self.credentials(granted_scopes=None)),
        )

        self.assertTrue(result["connected"])

    def test_an_empty_scope_is_treated_as_omitted_rather_than_a_refusal(self):
        # Google does not issue a token at all when nothing is granted, so an
        # empty value is the omitted case. Reading it literally rejected a
        # connection that had actually succeeded.
        for empty in ([], ""):
            with self.subTest(empty=empty):
                result, _, _ = self.complete(
                    self.start()[1],
                    flow=FakeFlow(self.credentials(granted_scopes=empty)),
                )
                self.assertTrue(result["connected"])
                self.db.query(GmailAccount).delete()
                self.db.commit()

    def test_the_unticked_gmail_box_is_still_refused_and_says_so(self):
        # The other scopes come back; only read access was left unticked.
        exc = self._expect_refusal(self.credentials(
            granted_scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"],
        ))

        self.assertEqual(exc.status_code, 422)
        # The message has to name the tickbox — "allow access" left users
        # re-running the same flow and failing the same way.
        self.assertIn("tickbox", exc.detail.lower())
        self.assertEqual(self.db.query(GmailAccount).count(), 0)

    def test_a_scope_string_is_accepted_in_place_of_a_list(self):
        result, _, _ = self.complete(
            self.start()[1],
            flow=FakeFlow(self.credentials(granted_scopes=" ".join(gmail.SCOPES))),
        )

        self.assertTrue(result["connected"])


class GmailReconnectLifecycleTests(GmailOAuthSecurityTests):
    """Disconnecting must leave nothing behind that breaks the next connect."""

    def _connect(self, email: str = "owner@gmail.com"):
        _, state = self.start()
        flow = FakeFlow(self.credentials())
        with (
            patch.object(gmail, "_build_flow", return_value=flow),
            patch.object(gmail, "_verify_google_identity", return_value=email),
        ):
            return gmail.gmail_oauth_complete(
                gmail.GmailOAuthComplete(code="google-code", state=state),
                user_id="owner",
                db=self.db,
            )

    def test_disconnect_clears_pending_state_so_a_stale_link_cannot_reconnect(self):
        self._connect()
        # A half-finished attempt left open in another tab.
        _, stale_state = self.start()
        self.assertEqual(self.db.query(GmailOAuthState).count(), 1)

        with patch.object(gmail, "revoke_encrypted_refresh_token") as revoke:
            revoke.return_value = SimpleNamespace(value="revoked")
            gmail.gmail_disconnect(user_id="owner", db=self.db)

        self.assertEqual(self.db.query(GmailAccount).count(), 0)
        self.assertEqual(self.db.query(GmailOAuthState).count(), 0)

        # The stale link must fail closed rather than silently reattaching.
        with (
            patch.object(gmail, "_build_flow", return_value=FakeFlow(self.credentials())),
            self.assertRaises(HTTPException) as caught,
        ):
            gmail.gmail_oauth_complete(
                gmail.GmailOAuthComplete(code="google-code", state=stale_state),
                user_id="owner",
                db=self.db,
            )
        self.assertEqual(caught.exception.status_code, 400)

    def test_reconnecting_a_different_mailbox_replaces_the_stored_identity(self):
        self._connect("first@gmail.com")
        with patch.object(gmail, "revoke_encrypted_refresh_token") as revoke:
            revoke.return_value = SimpleNamespace(value="revoked")
            gmail.gmail_disconnect(user_id="owner", db=self.db)

        result = self._connect("second@gmail.com")

        self.assertEqual(result["email_address"], "second@gmail.com")
        accounts = self.db.query(GmailAccount).all()
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0].email_address, "second@gmail.com")

    def test_a_refused_connection_leaves_no_account_to_confuse_the_retry(self):
        _, state = self.start()
        with (
            patch.object(gmail, "_build_flow", return_value=FakeFlow(
                self.credentials(granted_scopes=["openid"]))),
            self.assertRaises(HTTPException),
        ):
            gmail.gmail_oauth_complete(
                gmail.GmailOAuthComplete(code="google-code", state=state),
                user_id="owner",
                db=self.db,
            )

        self.assertEqual(self.db.query(GmailAccount).count(), 0)
        self.assertEqual(self.db.query(GmailOAuthState).count(), 0)
        # Retrying from scratch must work — this is the second attempt that
        # users report succeeding after they notice the tickbox.
        self.assertTrue(self._connect()["connected"])
