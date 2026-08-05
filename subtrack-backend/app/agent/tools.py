"""Anthropic schemas for user-scoped reads and inert action proposals."""
from datetime import datetime, time
from uuid import UUID

from sqlalchemy.orm import Session

from app.agent.actions import (
    ACTION_MODELS,
    ACTION_TOOL_DEFINITIONS,
    create_action_proposal,
)

from app.agent.finance import (
    commitment_changes,
    duplicate_payments,
    financial_overview,
    list_payments,
    payment_detail,
    review_detections,
    reminders_overview,
    saving_candidates,
    upcoming_charges,
)
from app.agent.research import ALTERNATIVE_RESEARCH_TOOL, research_alternatives
from app.models import Category


CATEGORIES = [item.value for item in Category]


def _utc_date(value: str, *, end_of_day: bool = False) -> datetime:
    """Interpret assistant date-only tool input using Subtrack's UTC policy."""
    parsed = datetime.strptime(value, "%Y-%m-%d").date()
    return datetime.combine(parsed, time.max if end_of_day else time.min)

READ_TOOL_DEFINITIONS = [
    {
        "name": "get_financial_overview",
        "description": (
            "Get the user's active tracked recurring-payment total, yearly equivalent, "
            "category breakdown, stated income share, and currency-quality metadata. "
            "This covers recurring commitments only, not all bank spending."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_recurring_payments",
        "description": (
            "List the user's active recurring payments, optionally narrowed to IDs selected "
            "in the UI, a category, or a name search. Use this before comparing payments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subscription_ids": {
                    "type": "array", "maxItems": 25,
                    "items": {"type": "string", "format": "uuid"},
                },
                "category": {"type": "string", "enum": CATEGORIES},
                "query": {"type": "string", "maxLength": 120},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "sort_by": {"type": "string", "enum": ["monthly_cost", "name", "next_due"]},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_recurring_payment",
        "description": (
            "Get one active recurring payment by ID. IDs from page context are only hints; "
            "this tool re-checks ownership before returning anything."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"subscription_id": {"type": "string", "format": "uuid"}},
            "required": ["subscription_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_upcoming_charges",
        "description": (
            "Get every projected charge occurrence for tracked recurring payments in either "
            "the next 1-730 days or an inclusive UTC date range. This is a forecast, not "
            "recorded transaction history. A weekly payment can appear many times."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": ["integer", "null"], "minimum": 1, "maximum": 730},
                "start_date": {"type": ["string", "null"], "format": "date"},
                "end_date": {"type": ["string", "null"], "format": "date"},
            },
            "required": ["days", "start_date", "end_date"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_commitment_changes",
        "description": (
            "Get additions, removals, and price changes in tracked monthly recurring "
            "commitments for the current month or a recent rolling period."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["current_month", "last_30_days", "last_90_days"],
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "find_duplicate_payments",
        "description": (
            "Find possible duplicate records in the user's tracked list. Suggestions are "
            "read-only and do not prove duplicate bank charges; the user must confirm."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_review_detections",
        "description": (
            "List pending or dismissed inbox detections, optionally limited to detection IDs "
            "visible on the review page. These are unapproved findings and are excluded from totals."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "detection_ids": {
                    "type": "array", "maxItems": 25,
                    "items": {"type": "string", "format": "uuid"},
                },
                "status": {"type": "string", "enum": ["pending", "dismissed"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_saving_candidates",
        "description": (
            "Get an evidence-led shortlist of large or recently increased recurring payments "
            "to review. Never call them unnecessary as fact and never imply cancellation is automatic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 10}},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_payment_reminders",
        "description": (
            "List the user's in-app renewal, cancellation, and trial reminders. "
            "Use visible reminder IDs from page context when the user refers to reminders on screen."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_ids": {
                    "type": "array", "maxItems": 25,
                    "items": {"type": "string", "format": "uuid"},
                },
                "status": {
                    "type": "string",
                    "enum": ["all", "due", "upcoming", "overdue", "dismissed"],
                },
                "horizon_days": {"type": "integer", "minimum": 1, "maximum": 730},
            },
            "additionalProperties": False,
        },
    },
    ALTERNATIVE_RESEARCH_TOOL,
]

TOOL_DEFINITIONS = READ_TOOL_DEFINITIONS + ACTION_TOOL_DEFINITIONS


def run_tool(
    tool_name: str,
    tool_input: dict,
    db: Session,
    user_id: str,
    *,
    thread_id: UUID | None = None,
    assistant_message_id: UUID | None = None,
):
    """Dispatch an allow-listed read or create an inert action proposal."""
    if tool_name in ACTION_MODELS:
        if not thread_id or not assistant_message_id:
            return {"error": "Action proposals require a conversation message"}
        return create_action_proposal(
            tool_name,
            tool_input,
            db,
            user_id,
            thread_id=thread_id,
            assistant_message_id=assistant_message_id,
        )
    if tool_name == "get_financial_overview":
        return financial_overview(db, user_id)
    if tool_name == "list_recurring_payments":
        return list_payments(db, user_id, tool_input)
    if tool_name == "get_recurring_payment":
        return payment_detail(db, user_id, tool_input.get("subscription_id", ""))
    if tool_name == "get_upcoming_charges":
        start_date = tool_input.get("start_date")
        end_date = tool_input.get("end_date")
        if bool(start_date) != bool(end_date):
            return {
                "error": "Both start_date and end_date are required for a custom forecast window."
            }
        try:
            if start_date and end_date:
                return upcoming_charges(
                    db,
                    user_id,
                    start_at=_utc_date(start_date),
                    end_at=_utc_date(end_date, end_of_day=True),
                )
            return upcoming_charges(db, user_id, tool_input.get("days") or 30)
        except (TypeError, ValueError) as exc:
            return {"error": str(exc)}
    if tool_name == "get_commitment_changes":
        return commitment_changes(db, user_id, tool_input.get("period", "current_month"))
    if tool_name == "find_duplicate_payments":
        return duplicate_payments(db, user_id)
    if tool_name == "list_review_detections":
        return review_detections(db, user_id, tool_input)
    if tool_name == "get_saving_candidates":
        return saving_candidates(db, user_id, tool_input.get("limit", 5))
    if tool_name == "list_payment_reminders":
        return reminders_overview(db, user_id, tool_input)
    if tool_name == "research_cheaper_alternatives":
        return research_alternatives(db, user_id, tool_input)
    return {"error": "Unknown assistant tool"}
