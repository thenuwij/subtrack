import os
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.agent.research import (  # noqa: E402
    _extract_answer,
    research_alternatives,
    utcnow,
)
from app.database import Base  # noqa: E402
from app.models import (  # noqa: E402
    AgentResearchCache,
    BillingCycle,
    Category,
    Subscription,
)


class AgentResearchTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.payment = Subscription(
            id=uuid4(), user_id="owner", name="Canva Pro",
            category=Category.software, amount=17.99, currency="AUD",
            cycle=BillingCycle.monthly, is_active=True,
        )
        self.db.add(self.payment)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def payload(self, payment=None):
        return {
            "subscription_id": str((payment or self.payment).id),
            "market": None,
            "requirements": "Templates and team sharing",
        }

    @staticmethod
    def completed():
        return {
            "status": "completed",
            "findings": "Option A is cheaper with fewer team features.",
            "sources": [{
                "title": "Option A pricing",
                "url": "https://example.com/pricing",
            }],
        }

    def test_successful_research_is_user_scoped_and_cached(self):
        with patch("app.agent.research._run_search", return_value=self.completed()) as search:
            first = research_alternatives(self.db, "owner", self.payload())
            second = research_alternatives(self.db, "owner", self.payload())

        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["market"], "Australia")
        self.assertEqual(first["market_source"], "inferred_from_currency")
        self.assertEqual(second["cache"], "cached")
        self.assertEqual(search.call_count, 1)
        self.assertEqual(self.db.query(AgentResearchCache).count(), 1)

        with patch("app.agent.research._run_search") as other_search:
            hidden = research_alternatives(self.db, "someone-else", self.payload())
        self.assertEqual(hidden["status"], "not_found")
        other_search.assert_not_called()

    def test_expired_cache_is_refreshed_without_a_duplicate_row(self):
        with patch("app.agent.research._run_search", return_value=self.completed()):
            research_alternatives(self.db, "owner", self.payload())
        cached = self.db.query(AgentResearchCache).one()
        cached.expires_at = utcnow() - timedelta(minutes=1)
        self.db.commit()

        refreshed = {
            **self.completed(),
            "findings": "Fresh current comparison.",
        }
        with patch("app.agent.research._run_search", return_value=refreshed) as search:
            result = research_alternatives(self.db, "owner", self.payload())

        self.assertEqual(result["findings"], "Fresh current comparison.")
        self.assertEqual(search.call_count, 1)
        self.assertEqual(self.db.query(AgentResearchCache).count(), 1)

    def test_personal_details_never_reach_the_search_provider(self):
        payment = Subscription(
            id=uuid4(), user_id="owner", name="Rent - 12/34 Example Street",
            category=Category.housing, amount=550, currency="AUD",
            cycle=BillingCycle.weekly, is_active=True,
        )
        self.db.add(payment)
        self.db.commit()
        response = SimpleNamespace(stop_reason="end_turn", content=[])
        with patch("app.agent.research.client.messages.create", return_value=response) as create:
            research_alternatives(self.db, "owner", {
                "subscription_id": str(payment.id),
                "market": None,
                "requirements": "Near 0412 345 678, email me at jane@example.com",
            })
        sent = str(create.call_args)
        for secret in ("12/34 Example Street", "0412 345 678", "jane@example.com"):
            self.assertNotIn(secret, sent)
        self.assertIn("Rent", sent)

    def test_hourly_limit_does_not_call_the_provider(self):
        for index in range(5):
            self.db.add(AgentResearchCache(
                id=uuid4(), user_id="owner", subscription_id=self.payment.id,
                fingerprint=f"fingerprint-{index}", market="Australia",
                result_json=self.completed(), expires_at=utcnow() + timedelta(hours=1),
                created_at=utcnow(),
            ))
        self.db.commit()
        another = Subscription(
            id=uuid4(), user_id="owner", name="Another service",
            category=Category.software, amount=30, currency="AUD",
            cycle=BillingCycle.monthly, is_active=True,
        )
        self.db.add(another)
        self.db.commit()

        with patch("app.agent.research._run_search") as search:
            result = research_alternatives(self.db, "owner", self.payload(another))
        self.assertEqual(result["status"], "rate_limited")
        search.assert_not_called()

    def test_citation_extraction_keeps_only_http_sources(self):
        response = SimpleNamespace(content=[
            SimpleNamespace(
                type="text",
                text="A grounded comparison.",
                citations=[
                    SimpleNamespace(
                        url="https://vendor.example/pricing",
                        title="Vendor pricing",
                    ),
                    SimpleNamespace(url="javascript:alert(1)", title="Unsafe"),
                ],
            ),
        ])
        text, sources = _extract_answer(response)
        self.assertEqual(text, "A grounded comparison.")
        self.assertEqual(sources, [{
            "title": "Vendor pricing",
            "url": "https://vendor.example/pricing",
        }])

    def test_citation_extraction_caps_unique_sources(self):
        response = SimpleNamespace(content=[
            SimpleNamespace(
                type="text",
                text="A grounded comparison.",
                citations=[
                    SimpleNamespace(
                        url=f"https://vendor-{index}.example/pricing",
                        title=f"Vendor {index} pricing",
                    )
                    for index in range(12)
                ],
            ),
        ])

        _, sources = _extract_answer(response)

        self.assertEqual(len(sources), 8)
        self.assertEqual(
            sources[-1]["url"],
            "https://vendor-7.example/pricing",
        )


if __name__ == "__main__":
    unittest.main()
