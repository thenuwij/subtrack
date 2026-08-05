import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from unittest.mock import patch

import anthropic
import httpx

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.database import Base  # noqa: E402
from app.gmail.analyzer import AnalysisOutcome, analyze_bounded  # noqa: E402
from app.gmail.scanner import (  # noqa: E402
    ReceiptCandidate,
    ScanResult,
    _fetch_all,
)
from app.models import GmailAccount  # noqa: E402
from app.routers import gmail as gmail_router  # noqa: E402


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class GmailScanPipelineTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    @staticmethod
    def candidate(index: int) -> ReceiptCandidate:
        return ReceiptCandidate(
            message_id=f"message-{index}",
            sender_domain=f"vendor-{index}.example",
            merchant=f"Vendor {index}",
            subject="Your subscription renewal receipt",
            date="2026-08-01",
            amount=10,
            currency="AUD",
            confidence="high",
            excerpt="Monthly subscription payment received.",
        )

    def test_fetch_deadline_returns_partial_without_starting_another_batch(self):
        with patch("app.gmail.scanner.time.monotonic", return_value=20), patch(
            "app.gmail.scanner._fetch_batch"
        ) as fetch, self.assertLogs("app.gmail.scanner", level="WARNING"):
            candidates, timed_out = _fetch_all(object(), ["one", "two"], deadline=10)

        self.assertEqual(candidates, [])
        self.assertTrue(timed_out)
        fetch.assert_not_called()

    def test_analysis_prioritises_and_caps_domains_to_three_parallel_calls(self):
        candidates = [self.candidate(index) for index in range(30)]
        with patch("app.gmail.analyzer._analyze_chunk", return_value=[]) as analyze:
            outcome = analyze_bounded(candidates)

        self.assertEqual(analyze.call_count, 3)
        self.assertEqual(outcome.selected_domains, 24)
        self.assertEqual(outcome.processed_domains, 24)
        self.assertEqual(outcome.total_domains, 30)
        self.assertTrue(outcome.truncated)

    def test_scan_finalises_instead_of_leaving_running_status(self):
        run_id = "run-1"
        db = self.Session()
        db.add(GmailAccount(
            user_id="owner",
            email_address="owner@example.com",
            refresh_token_encrypted="encrypted",
            scan_status="running",
            scan_run_id=run_id,
            scan_started_at=utcnow(),
            scan_heartbeat_at=utcnow(),
        ))
        db.commit()
        db.close()

        scan_result = ScanResult([], 0, 0, 0, False)
        outcome = AnalysisOutcome([], 0, 0, 0, 0, False, False)
        with patch.object(gmail_router, "SessionLocal", self.Session), patch.object(
            gmail_router, "decrypt_token", return_value="token"
        ), patch("app.gmail.scanner.scan", return_value=scan_result), patch(
            "app.gmail.analyzer.analyze_bounded", return_value=outcome
        ), patch("app.gmail.analyzer.find_similar", return_value={}):
            gmail_router._run_scan("owner", run_id)

        db = self.Session()
        account = db.get(GmailAccount, "owner")
        self.assertEqual(account.scan_status, "done")
        self.assertEqual(account.scan_stage, "complete")
        self.assertIsNotNone(account.last_scanned_at)
        db.close()

    def test_unexpected_pipeline_error_becomes_retryable_status(self):
        run_id = "run-2"
        db = self.Session()
        db.add(GmailAccount(
            user_id="owner",
            email_address="owner@example.com",
            refresh_token_encrypted="encrypted",
            scan_status="running",
            scan_run_id=run_id,
            scan_started_at=utcnow(),
            scan_heartbeat_at=utcnow(),
        ))
        db.commit()
        db.close()

        with patch.object(gmail_router, "SessionLocal", self.Session), patch.object(
            gmail_router, "decrypt_token", return_value="token"
        ), patch("app.gmail.scanner.scan", side_effect=RuntimeError("boom")):
            with self.assertLogs("app.routers.gmail", level="ERROR"):
                gmail_router._run_scan("owner", run_id)

        db = self.Session()
        account = db.get(GmailAccount, "owner")
        self.assertEqual(account.scan_status, "error")
        self.assertIsNone(account.scan_stage)
        self.assertIn("Try again", account.scan_error)
        db.close()

    def test_staleness_honours_heartbeat_and_absolute_two_minute_budget(self):
        account = GmailAccount(
            user_id="owner",
            email_address="owner@example.com",
            refresh_token_encrypted="encrypted",
            scan_status="running",
            scan_started_at=utcnow() - timedelta(seconds=30),
            scan_heartbeat_at=utcnow(),
        )
        self.assertFalse(gmail_router._scan_is_stale(account))
        account.scan_heartbeat_at = utcnow() - timedelta(minutes=4)
        self.assertTrue(gmail_router._scan_is_stale(account))
        account.scan_started_at = utcnow() - timedelta(hours=1)
        account.scan_heartbeat_at = utcnow()
        self.assertTrue(gmail_router._scan_is_stale(account))

    def test_user_facing_budget_leaves_polling_headroom(self):
        self.assertLessEqual(gmail_router.SCAN_TIME_LIMIT_SECONDS, 105)


if __name__ == "__main__":
    unittest.main()


class AnalysisRetryTests(unittest.TestCase):
    """A momentary rate limit must not discard a whole batch of domains.

    The SDK's own retries are off so one slow call cannot overrun the scan
    budget. That left zero tolerance: a single 429 — which comes back in
    milliseconds — threw away all eight sender domains in the call, and three
    unlucky calls failed the entire scan.
    """

    def setUp(self):
        self.calls = 0
        self.slept = []

    def _patched(self, side_effects, deadline=None):
        """Run _analyze_chunk against a stubbed client, counting attempts."""
        import app.gmail.analyzer as az

        def fake_parse(**kwargs):
            outcome = side_effects[min(self.calls, len(side_effects) - 1)]
            self.calls += 1
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        stub = mock.Mock()
        stub.messages.parse.side_effect = fake_parse
        with mock.patch.object(az, "client", stub), \
                mock.patch.object(az.time, "sleep", self.slept.append):
            return az._analyze_chunk(["vendor.example"], {"vendor.example": []}, deadline)

    def _ok_response(self):
        response = mock.Mock()
        response.stop_reason = "end_turn"
        response.parsed_output.subscriptions = []
        return response

    def _rate_limited(self):
        return anthropic.RateLimitError(
            "rate limited",
            response=httpx.Response(429, request=httpx.Request("POST", "https://x")),
            body=None,
        )

    def test_a_rate_limit_is_retried_and_then_succeeds(self):
        result = self._patched([self._rate_limited(), self._ok_response()])

        self.assertEqual(result, [])
        self.assertEqual(self.calls, 2)
        self.assertEqual(len(self.slept), 1)

    def test_retries_are_bounded_rather_than_endless(self):
        import app.gmail.analyzer as az

        with self.assertRaises(anthropic.RateLimitError):
            self._patched([self._rate_limited()])

        self.assertEqual(self.calls, az.ANALYSIS_MAX_RETRIES + 1)

    def test_a_retry_that_cannot_finish_in_the_budget_is_not_started(self):
        # Deadline already past: failing now leaves the remaining batches their
        # share of the budget instead of spending it on a doomed call.
        with self.assertRaises(anthropic.RateLimitError):
            self._patched([self._rate_limited()], deadline=time.monotonic())

        self.assertEqual(self.calls, 1)
        self.assertEqual(self.slept, [])

    def test_a_timeout_is_not_retried(self):
        # Retrying a timeout costs another full call timeout and would push the
        # scan past the deadline that timeout exists to protect.
        timeout = anthropic.APITimeoutError(request=httpx.Request("POST", "https://x"))

        with self.assertRaises(anthropic.APITimeoutError):
            self._patched([timeout])

        self.assertEqual(self.calls, 1)

    def test_a_permanent_client_error_is_not_retried(self):
        bad_request = anthropic.BadRequestError(
            "bad request",
            response=httpx.Response(400, request=httpx.Request("POST", "https://x")),
            body=None,
        )

        with self.assertRaises(anthropic.BadRequestError):
            self._patched([bad_request])

        self.assertEqual(self.calls, 1)

    def test_provider_retry_after_is_honoured_over_the_default_backoff(self):
        capped = anthropic.RateLimitError(
            "rate limited",
            response=httpx.Response(
                429,
                headers={"retry-after": "3"},
                request=httpx.Request("POST", "https://x"),
            ),
            body=None,
        )

        self._patched([capped, self._ok_response()])

        self.assertEqual(self.slept, [3.0])
