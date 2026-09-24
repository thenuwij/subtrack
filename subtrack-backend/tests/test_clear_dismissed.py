import os
import unittest
from uuid import uuid4

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
    DetectedSubscription,
    DetectionStatus,
)
from app.routers.detected import clear_dismissed, clear_one_dismissed  # noqa: E402


class ClearDismissedTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def detection(self, user_id="owner", status=DetectionStatus.dismissed):
        row = DetectedSubscription(
            id=uuid4(),
            user_id=user_id,
            merchant="Vendor Pro",
            sender_domain="vendor.example",
            product_key=f"vendor-{uuid4().hex[:6]}",
            category=Category.software,
            cycle=BillingCycle.monthly,
            interval_unit="month",
            interval_count=1,
            cadence_confidence="high",
            amount=19.99,
            currency="AUD",
            confidence="high",
            charge_count=3,
            status=status,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def remaining(self):
        return {row.id for row in self.db.query(DetectedSubscription).all()}

    def test_clear_one_deletes_only_that_dismissed_detection(self):
        target = self.detection()
        other = self.detection()

        result = clear_one_dismissed(target.id, user_id="owner", db=self.db)

        self.assertEqual(result, {"cleared": 1})
        self.assertEqual(self.remaining(), {other.id})

    def test_clear_one_refuses_pending_and_approved_detections(self):
        pending = self.detection(status=DetectionStatus.pending)
        approved = self.detection(status=DetectionStatus.approved)

        for row in (pending, approved):
            with self.assertRaises(HTTPException) as caught:
                clear_one_dismissed(row.id, user_id="owner", db=self.db)
            self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.remaining(), {pending.id, approved.id})

    def test_clear_one_hides_other_users_detections(self):
        foreign = self.detection(user_id="someone-else")

        with self.assertRaises(HTTPException) as caught:
            clear_one_dismissed(foreign.id, user_id="owner", db=self.db)

        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(self.remaining(), {foreign.id})

    def test_clear_all_deletes_only_the_users_dismissed_detections(self):
        self.detection()
        self.detection()
        pending = self.detection(status=DetectionStatus.pending)
        approved = self.detection(status=DetectionStatus.approved)
        foreign = self.detection(user_id="someone-else")

        result = clear_dismissed(user_id="owner", db=self.db)

        self.assertEqual(result, {"cleared": 2})
        self.assertEqual(self.remaining(), {pending.id, approved.id, foreign.id})

    def test_clear_all_with_nothing_dismissed_is_a_no_op(self):
        pending = self.detection(status=DetectionStatus.pending)

        result = clear_dismissed(user_id="owner", db=self.db)

        self.assertEqual(result, {"cleared": 0})
        self.assertEqual(self.remaining(), {pending.id})


if __name__ == "__main__":
    unittest.main()
