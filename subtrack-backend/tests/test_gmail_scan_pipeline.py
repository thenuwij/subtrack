import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

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

    def test_staleness_uses_heartbeat_not_original_start(self):
        account = GmailAccount(
            user_id="owner",
            email_address="owner@example.com",
            refresh_token_encrypted="encrypted",
            scan_status="running",
            scan_started_at=utcnow() - timedelta(hours=1),
            scan_heartbeat_at=utcnow(),
        )
        self.assertFalse(gmail_router._scan_is_stale(account))
        account.scan_heartbeat_at = utcnow() - timedelta(minutes=4)
        self.assertTrue(gmail_router._scan_is_stale(account))

    def test_user_facing_budget_leaves_polling_headroom(self):
        self.assertLessEqual(gmail_router.SCAN_TIME_LIMIT_SECONDS, 105)


if __name__ == "__main__":
    unittest.main()
