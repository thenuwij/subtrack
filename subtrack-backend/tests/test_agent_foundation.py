import os
import unittest
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Settings are evaluated while importing the router. The real values are not
# used by these unit tests, but harmless defaults keep the module importable in
# a clean CI environment.
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.agent.tools import TOOL_DEFINITIONS  # noqa: E402
from app.database import Base  # noqa: E402
from app.models import AgentMessage, AgentThread  # noqa: E402
from app.routers.agent import (  # noqa: E402
    _get_thread,
    _model_history,
    _normalise_title,
    _public_error,
    _sse,
    _title_from_message,
    _utcnow,
    list_messages,
)


class AgentFoundationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_phase_one_tools_are_read_only(self):
        names = {tool["name"] for tool in TOOL_DEFINITIONS}
        self.assertEqual(names, {"get_subscriptions", "get_monthly_income"})

    def test_threads_cannot_be_loaded_for_another_user(self):
        from fastapi import HTTPException

        db = self.Session()
        thread = AgentThread(id=uuid4(), user_id="owner", title="Private")
        db.add(thread)
        db.commit()
        with self.assertRaises(HTTPException) as caught:
            _get_thread(db, thread.id, "someone-else")
        self.assertEqual(caught.exception.status_code, 404)
        db.close()

    def test_titles_are_compact_and_bounded(self):
        self.assertEqual(_normalise_title("  hello\n  there "), "hello there")
        generated = _title_from_message("word " * 40)
        self.assertLessEqual(len(generated), 48)
        self.assertTrue(generated.endswith("…"))

    def test_sse_payload_is_framed_and_compact(self):
        self.assertEqual(
            _sse("delta", {"text": "hello"}),
            'event: delta\ndata: {"text":"hello"}\n\n',
        )

    def test_failures_have_safe_user_facing_copy(self):
        self.assertIn("saved", _public_error("timed_out").lower())
        self.assertNotIn("exception", _public_error("agent_error").lower())

    def test_history_skips_failed_placeholders_and_coalesces_roles(self):
        db = self.Session()
        thread = AgentThread(
            id=uuid4(), user_id="user-1", title="Test", next_message_sequence=4
        )
        db.add(thread)
        db.flush()
        first = AgentMessage(
            id=uuid4(), thread_id=thread.id, user_id="user-1",
            role="user", sequence=1, content="First question", status="completed",
        )
        failed = AgentMessage(
            id=uuid4(), thread_id=thread.id, user_id="user-1",
            role="assistant", sequence=2, content="", status="failed", reply_to_id=first.id,
        )
        second = AgentMessage(
            id=uuid4(), thread_id=thread.id, user_id="user-1",
            role="user", sequence=3, content="Second question", status="completed",
        )
        answer = AgentMessage(
            id=uuid4(), thread_id=thread.id, user_id="user-1",
            role="assistant", sequence=4, content="Answer", status="completed", reply_to_id=second.id,
        )
        db.add_all([first, failed, second, answer])
        db.commit()

        self.assertEqual(_model_history(db, thread.id), [
            {"role": "user", "content": "First question\n\nSecond question"},
            {"role": "assistant", "content": "Answer"},
        ])
        db.close()

    def test_stale_stream_is_recovered_as_retryable_failure(self):
        db = self.Session()
        thread = AgentThread(
            id=uuid4(), user_id="user-1", title="Interrupted",
            next_message_sequence=1,
        )
        pending = AgentMessage(
            id=uuid4(), thread_id=thread.id, user_id="user-1",
            role="assistant", sequence=1, content="", status="streaming",
            updated_at=_utcnow() - timedelta(minutes=10),
        )
        db.add_all([thread, pending])
        db.commit()

        page = list_messages(
            thread.id, before=None, limit=50, user_id="user-1", db=db
        )

        self.assertEqual(page["messages"][0]["status"], "failed")
        self.assertEqual(page["messages"][0]["error_code"], "stream_interrupted")
        db.close()


if __name__ == "__main__":
    unittest.main()
