from sqlalchemy.orm import Session
from app.models import Subscription, UserPreference

# ── Tool definitions (what Claude sees) ──────────────────────────────────────
# This is the list you pass to the Claude API so it knows what tools exist.
# Each tool needs: a name, a description (Claude reads this to decide when to use it),
# and an input_schema (what arguments it expects).

TOOL_DEFINITIONS = [
    {
        "name": "get_subscriptions",
        "description": "Get all active recurring payments for the user, including rent, bills, memberships, and subscriptions. Use when asked about recurring bills or monthly commitments.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_monthly_income",
        "description": "Get the user's stated monthly income and base currency. Use when asked about affordability or what share of their income something takes up.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
]


# ── Tool functions (what actually runs) ───────────────────────────────────────
# These are called by the agent loop when Claude requests a tool.
# Every function takes the DB session and user_id for security —
# we never let Claude query data for other users.

def get_subscriptions(db: Session, user_id: str):
    subs = db.query(Subscription).filter(
        Subscription.user_id == user_id,
        Subscription.is_active == True
    ).all()

    return [
        {
            "id": str(s.id),
            "name": s.name,
            "amount": s.amount,
            "currency": s.currency,
            "converted_amount": s.converted_amount,
            "cycle": s.cycle.value if hasattr(s.cycle, 'value') else s.cycle,
            "category": s.category.value if hasattr(s.category, 'value') else s.category,
            "next_due": s.next_due.strftime("%Y-%m-%d") if s.next_due else None
        }
        for s in subs
    ]


def get_monthly_income(db: Session, user_id: str):
    pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    if not pref or pref.monthly_income is None:
        return {"monthly_income": None, "currency": pref.base_currency if pref else "AUD"}
    return {"monthly_income": pref.monthly_income, "currency": pref.base_currency}


# ── Dispatcher ────────────────────────────────────────────────────────────────
# When Claude says "call get_subscriptions with these args",
# this function maps the tool name to the right Python function.
# It's just a lookup — nothing clever.

def run_tool(tool_name: str, tool_input: dict, db: Session, user_id: str):
    if tool_name == "get_subscriptions":
        return get_subscriptions(db, user_id)
    elif tool_name == "get_monthly_income":
        return get_monthly_income(db, user_id)
    return {"error": f"Unknown tool: {tool_name}"}
