import asyncio
import os
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from typing import ClassVar
from unittest.mock import patch

import httpx
import jwt
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.config import Settings, settings
from app.middleware import auth
from app.routers import meta


async def _request(app, method: str, path: str, **kwargs):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


class _JwksResponse:
    def __init__(self, document):
        self.document = document

    def raise_for_status(self):
        return None

    def json(self):
        return self.document


class JwksHardeningTests(unittest.TestCase):
    jwks_url = "https://project.supabase.co/auth/v1/.well-known/jwks.json"
    jwks: ClassVar[dict] = {"keys": [{"kid": "known", "kty": "EC"}]}

    def setUp(self):
        auth._reset_jwks_cache_for_tests()

    def tearDown(self):
        auth._reset_jwks_cache_for_tests()

    def _seed_cache(self, *, fetched_at=100.0, last_attempt_at=100.0):
        with auth._jwks_lock:
            auth._jwks_cache.update(
                {
                    "url": self.jwks_url,
                    "keys": self.jwks,
                    "fetched_at": fetched_at,
                    "last_attempt_at": last_attempt_at,
                    "negative_kids": {},
                }
            )

    def test_fresh_cache_avoids_upstream_request(self):
        self._seed_cache()
        with (
            patch.object(settings, "supabase_url", "https://project.supabase.co"),
            patch.object(auth, "_now", return_value=200.0),
            patch.object(auth.httpx, "get") as get,
        ):
            self.assertIs(auth._fetch_jwks(), self.jwks)
        get.assert_not_called()

    def test_unknown_kid_refreshes_once_then_uses_bounded_negative_cache(self):
        self._seed_cache()
        with (
            patch.object(settings, "supabase_url", "https://project.supabase.co"),
            patch.object(auth, "_now", return_value=200.0),
            patch.object(
                auth.httpx,
                "get",
                return_value=_JwksResponse(self.jwks),
            ) as get,
        ):
            self.assertIsNone(auth._find_jwk("rotated-but-absent"))
            self.assertIsNone(auth._find_jwk("rotated-but-absent"))
        self.assertEqual(get.call_count, 1)

    def test_stale_keys_are_served_during_refresh_failure_with_cooldown(self):
        self._seed_cache(fetched_at=10.0, last_attempt_at=10.0)
        now = auth._JWKS_TTL_SECONDS + 20.0
        with (
            patch.object(settings, "supabase_url", "https://project.supabase.co"),
            patch.object(auth, "_now", return_value=now),
            patch.object(
                auth.httpx,
                "get",
                side_effect=RuntimeError("temporary outage"),
            ) as get,
            self.assertLogs("app.middleware.auth", level="WARNING"),
        ):
            self.assertIs(auth._fetch_jwks(), self.jwks)
            self.assertIs(auth._fetch_jwks(), self.jwks)
        self.assertEqual(get.call_count, 1)

    def test_concurrent_cold_requests_share_one_refresh(self):
        entered_upstream = threading.Event()
        release_upstream = threading.Event()
        second_worker_started = threading.Event()
        call_count = 0
        count_lock = threading.Lock()

        def fake_get(*args, **kwargs):
            nonlocal call_count
            with count_lock:
                call_count += 1
            entered_upstream.set()
            if not release_upstream.wait(timeout=2):
                raise AssertionError("test did not release the upstream request")
            return _JwksResponse(self.jwks)

        def fetch(marker=None):
            if marker is not None:
                marker.set()
            return auth._fetch_jwks()

        with (
            patch.object(settings, "supabase_url", "https://project.supabase.co"),
            patch.object(auth.httpx, "get", side_effect=fake_get),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            first = pool.submit(fetch)
            self.assertTrue(entered_upstream.wait(timeout=2))
            second = pool.submit(fetch, second_worker_started)
            self.assertTrue(second_worker_started.wait(timeout=2))
            release_upstream.set()
            self.assertEqual(first.result(timeout=2), self.jwks)
            self.assertEqual(second.result(timeout=2), self.jwks)

        self.assertEqual(call_count, 1)


class TokenIssuerTests(unittest.TestCase):
    secret = "issuer-test-secret-with-at-least-32-bytes"
    issuer = "https://project.supabase.co/auth/v1"

    def _credentials(self, issuer=None, *, kid=None):
        claims = {
            "sub": "user-123",
            "aud": "authenticated",
            "exp": int(time.time()) + 300,
        }
        if issuer is not None:
            claims["iss"] = issuer
        headers = {"kid": kid} if kid is not None else None
        token = jwt.encode(claims, self.secret, algorithm="HS256", headers=headers)
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    def test_configured_supabase_issuer_is_required_and_accepted(self):
        with (
            patch.object(settings, "supabase_jwt_secret", self.secret),
            patch.object(settings, "supabase_url", "https://project.supabase.co"),
        ):
            self.assertEqual(
                auth.verify_token(self._credentials(self.issuer)), "user-123"
            )
            with self.assertRaises(HTTPException) as caught:
                auth.verify_token(self._credentials("https://attacker.example/auth/v1"))
        self.assertEqual(caught.exception.status_code, 401)

    def test_local_hs256_compatibility_does_not_require_issuer(self):
        with (
            patch.object(settings, "supabase_jwt_secret", self.secret),
            patch.object(settings, "supabase_url", ""),
        ):
            self.assertEqual(auth.verify_token(self._credentials()), "user-123")

    def test_legacy_hs256_token_with_kid_stays_compatible(self):
        with (
            patch.object(settings, "supabase_jwt_secret", self.secret),
            patch.object(settings, "supabase_url", "https://project.supabase.co"),
            patch.object(auth, "_find_jwk") as find_jwk,
        ):
            self.assertEqual(
                auth.verify_token(self._credentials(self.issuer, kid="legacy-key")),
                "user-123",
            )
        find_jwk.assert_not_called()

    def test_access_token_must_have_an_expiry(self):
        token = jwt.encode(
            {
                "sub": "user-123",
                "aud": "authenticated",
                "iss": self.issuer,
            },
            self.secret,
            algorithm="HS256",
        )
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=token,
        )
        with (
            patch.object(settings, "supabase_jwt_secret", self.secret),
            patch.object(settings, "supabase_url", "https://project.supabase.co"),
            self.assertRaises(HTTPException) as caught,
        ):
            auth.verify_token(credentials)
        self.assertEqual(caught.exception.status_code, 401)


class ProductionSettingsTests(unittest.TestCase):
    def _settings(self, **overrides):
        values = {
            "database_url": "postgresql://example.invalid/subtrack?sslmode=require",
            "supabase_jwt_secret": "production-test-secret-at-least-32-bytes",
            "supabase_url": "https://project.supabase.co",
            "allowed_origins": "https://app.example.com",
            "frontend_url": "https://app.example.com",
            "environment": "production",
            "anthropic_api_key": "test-key",
            "google_redirect_uri": "https://api.example.com/gmail/callback",
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    def test_valid_production_urls_are_accepted(self):
        configured = self._settings()
        self.assertEqual(configured.frontend_url, "https://app.example.com")

    def test_insecure_or_ambiguous_production_urls_are_rejected(self):
        invalid_overrides = (
            {"database_url": "sqlite:///ephemeral.db"},
            {"database_url": "postgresql://example.invalid"},
            {"database_url": "postgresql://example.invalid/subtrack"},
            {"database_url": "postgresql://example.invalid/subtrack?sslmode=disable"},
            {"supabase_jwt_secret": "too-short"},
            {"anthropic_api_key": "   "},
            {"frontend_url": "http://app.example.com"},
            {"allowed_origins": "*"},
            {"allowed_origins": "https://admin.example.com"},
            {"google_redirect_uri": "http://api.example.com/gmail/callback"},
            {"supabase_url": "https://project.supabase.co/auth/v1"},
            {"frontend_url": "https://app.example.com "},
            {
                "frontend_url": "https://secure.localhost",
                "allowed_origins": "https://secure.localhost",
            },
        )
        for overrides in invalid_overrides:
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                self._settings(**overrides)

    def test_unknown_environment_and_invalid_pool_bounds_are_rejected(self):
        for overrides in (
            {"environment": "prodution"},
            {"database_pool_size": 0},
            {"database_pool_size": 51},
            {"database_max_overflow": -1},
            {"database_pool_timeout": 0},
            {"database_pool_timeout": 121},
            {"database_connect_timeout": 0},
            {"database_connect_timeout": 31},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                Settings(
                    _env_file=None,
                    database_url="sqlite://",
                    supabase_jwt_secret="test-secret",
                    anthropic_api_key="test-key",
                    **overrides,
                )

    def test_unset_frontend_url_falls_back_to_the_first_allowed_origin(self):
        """A deployment that predates FRONTEND_URL must not redirect to localhost.

        This exact gap sent the deployed Gmail handshake to a developer's
        machine: the setting was added to the blueprint, the running service
        never received it, and the hard-coded localhost default won.
        """
        configured = self._settings(
            frontend_url="",
            allowed_origins="https://app.example.com,https://alt.example.com",
        )
        self.assertEqual(configured.frontend_url, "https://app.example.com")

    def test_explicit_frontend_url_still_wins_over_the_fallback(self):
        configured = self._settings(
            frontend_url="https://alt.example.com",
            allowed_origins="https://app.example.com,https://alt.example.com",
        )
        self.assertEqual(configured.frontend_url, "https://alt.example.com")

    def test_development_keeps_local_http_defaults(self):
        configured = Settings(
            _env_file=None,
            database_url="sqlite://",
            supabase_jwt_secret="test-secret",
            anthropic_api_key="test-key",
            environment="development",
        )
        self.assertEqual(configured.allowed_origins, "http://localhost:3000")
        self.assertEqual(configured.frontend_url, "http://localhost:3000")


class ApiBoundaryTests(unittest.TestCase):
    def test_response_security_headers_and_exact_cors_origin(self):
        from app.main import app

        with patch.object(settings, "environment", "production"):
            response = asyncio.run(_request(app, "GET", "/meta/capabilities"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(
            response.headers["strict-transport-security"],
            "max-age=31536000; includeSubDomains",
        )
        self.assertTrue(response.headers["x-request-id"])

        allowed = asyncio.run(
            _request(
                app,
                "OPTIONS",
                "/meta/capabilities",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                },
            )
        )
        self.assertEqual(
            allowed.headers.get("access-control-allow-origin"),
            "http://localhost:3000",
        )
        denied = asyncio.run(
            _request(
                app,
                "OPTIONS",
                "/meta/capabilities",
                headers={
                    "Origin": "https://attacker.example",
                    "Access-Control-Request-Method": "GET",
                },
            )
        )
        self.assertIsNone(denied.headers.get("access-control-allow-origin"))

    def test_unhandled_error_is_sanitized_and_keeps_cors_and_request_id(self):
        from app.main import app

        with patch(
            "app.main.engine.connect",
            side_effect=RuntimeError("database password must not leak"),
        ):
            response = asyncio.run(
                _request(
                    app,
                    "GET",
                    "/health/ready",
                    headers={"Origin": "http://localhost:3000"},
                )
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.headers["access-control-allow-origin"], "http://localhost:3000"
        )
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertTrue(response.headers["x-request-id"])
        self.assertEqual(
            response.json(),
            {
                "detail": "Internal server error",
                "request_id": response.headers["x-request-id"],
            },
        )
        self.assertNotIn("password", response.text)


class CapabilityMetadataTests(unittest.TestCase):
    def test_capability_contract_and_release_are_machine_readable(self):
        with (
            patch.dict(
                os.environ,
                {"RENDER_GIT_COMMIT": "abc123", "RENDER_SERVICE_NAME": "subtrack-api"},
            ),
            patch.object(settings, "environment", "production"),
            patch("app.routers.gmail.gmail_is_configured", return_value=True),
        ):
            payload = meta.get_capabilities()

        self.assertEqual(payload["api"]["version"], "1")
        self.assertEqual(payload["release"]["commit"], "abc123")
        self.assertEqual(
            payload["capabilities"],
            {
                "flexible_cadence_v1": True,
                "lifecycle_v1": True,
                "exact_forecast_v1": True,
                "variable_amounts_v1": True,
                "server_equivalents_v1": True,
                "gmail_secure_oauth_v1": True,
                "data_export_v1": True,
                "app_data_deletion_v1": True,
                "gmail_configured": True,
            },
        )
        self.assertIn(
            "/meta/capabilities", {route.path for route in meta.router.routes}
        )


if __name__ == "__main__":
    unittest.main()


class SchemaReadinessTests(unittest.TestCase):
    """A reachable database is not a working one.

    Shipping code whose migrations had not run left every signed-in page
    returning 500 while the deploy looked healthy: the queries referenced
    columns that did not exist yet. Readiness has to fail instead, so the
    release stops and the previous version keeps serving — which is the only
    safety net where the migration cannot be run automatically before release.
    """

    def _ready(self):
        from app.main import app

        return asyncio.run(_request(app, "GET", "/health/ready"))

    def test_a_matching_schema_reports_its_revision(self):
        with patch("app.main._expected_schema_revision", return_value="0011_x"), \
                patch("app.main._schema_revision", return_value="0011_x"):
            response = self._ready()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["schema_revision"], "0011_x")

    def test_a_database_behind_the_code_is_not_ready(self):
        with patch("app.main._expected_schema_revision", return_value="0012_new"), \
                patch("app.main._schema_revision", return_value="0011_x"):
            response = self._ready()

        self.assertEqual(response.status_code, 503)
        detail = response.json()["detail"]
        # The message has to name both revisions and the command that fixes it;
        # a bare "not ready" sends someone hunting through logs.
        self.assertIn("0011_x", detail)
        self.assertIn("0012_new", detail)
        self.assertIn("migrate.py", detail)

    def test_an_undeterminable_revision_never_blocks_a_release(self):
        # Local SQLite has no alembic_version table, and a packaging change
        # could hide the migration scripts. Neither is evidence of a mismatch,
        # so neither may fail a deploy.
        cases = ((None, "0011_x"), ("0011_x", None), (None, None))
        for expected, applied in cases:
            with self.subTest(expected=expected, applied=applied):
                with patch("app.main._expected_schema_revision", return_value=expected), \
                        patch("app.main._schema_revision", return_value=applied):
                    self.assertEqual(self._ready().status_code, 200)

    def test_the_expected_revision_resolves_from_the_real_migrations(self):
        # Guards the alembic.ini path: a wrong one degrades the check to a
        # permanent no-op that still returns 200 and protects nothing.
        from app.main import _expected_schema_revision

        _expected_schema_revision.cache_clear()
        self.assertIsNotNone(_expected_schema_revision())
