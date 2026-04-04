from sqlalchemy.orm import Session
from datetime import datetime
from app.models import Expense, Subscription, Budget, Income, SavingsGoal

# ── Tool definitions (what Claude sees) ──────────────────────────────────────
# This is the list you pass to the Claude API so it knows what tools exist.
# Each tool needs: a name, a description (Claude reads this to decide when to use it),
# and an input_schema (what arguments it expects).

TOOL_DEFINITIONS = [
    {
        "name": "get_monthly_expenses",
        "description": "Get all expenses for a given month. Use this when the user asks about spending, transactions, or expenses for a specific month.",
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {
                    "type": "string",
                    "description": "Month in YYYY-MM format, e.g. '2026-04'"
                },
                "category": {
                    "type": "string",
                    "description": "Optional category filter e.g. 'food', 'transport'",
                }
            },
            "required": ["month"]
        }
    },
    {
        "name": "get_subscriptions",
        "description": "Get all active subscriptions for the user. Use when asked about recurring bills, subscriptions, or monthly commitments.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_budgets",
        "description": "Get all budget limits the user has set by category.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_savings_goals",
        "description": "Get all savings goals and their current progress.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_income_entries",
        "description": "Get recent income entries. Use when asked about earnings, income, or affordability.",
        "input_schema": {
            "type": "object",
            "properties": {
                "months": {
                    "type": "integer",
                    "description": "How many months back to look. Default 3."
                }
            },
            "required": []
        }
    },
    {
        "name": "create_expense",
        "description": "Log a new expense. Only call this after confirming the details with the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name":     { "type": "string",  "description": "Expense name e.g. 'Woolworths'" },
                "amount":   { "type": "number",  "description": "Amount spent" },
                "category": { "type": "string",  "description": "Category: food, transport, software, streaming, cloud, utilities, fitness, other" },
                "date":     { "type": "string",  "description": "Date in YYYY-MM-DD format" },
                "currency": { "type": "string",  "description": "Currency code e.g. AUD, USD" }
            },
            "required": ["name", "amount", "category", "date", "currency"]
        }
    },
    {
        "name": "delete_expense",
        "description": "Delete an expense by ID. Only call this after confirming with the user which expense to delete.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expense_id": {
                    "type": "string",
                    "description": "The UUID of the expense to delete"
                }
            },
            "required": ["expense_id"]
        }
    },
    {
        "name": "delete_subscription",
        "description": "Delete a subscription by ID. Only call this after confirming with the user which subscription to delete.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subscription_id": {
                    "type": "string",
                    "description": "The UUID of the subscription to delete"
                }
            },
            "required": ["subscription_id"]
        }
    },
    {
        "name": "delete_savings_goal",
        "description": "Delete a savings goal by ID. Only call this after confirming with the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "goal_id": {
                    "type": "string",
                    "description": "The UUID of the savings goal to delete"
                }
            },
            "required": ["goal_id"]
        }
    },
    {
        "name": "create_income",
        "description": "Log a new income entry for the user. Only call this after confirming details with the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount":    { "type": "number", "description": "Income amount" },
                "currency":  { "type": "string", "description": "Currency code e.g. AUD, USD" },
                "frequency": { "type": "string", "description": "One of: weekly, fortnightly, monthly, irregular" },
                "source":    { "type": "string", "description": "Income source e.g. 'Salary', 'Freelance'" },
                "date":      { "type": "string", "description": "Date in YYYY-MM-DD format" }
            },
            "required": ["amount", "currency", "frequency", "date"]
        }
    },
    {
        "name": "create_savings_goal",
        "description": "Create a new savings goal for the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name":          { "type": "string", "description": "Goal name e.g. 'Dyson Vacuum'" },
                "target_amount": { "type": "number", "description": "Target amount to save" },
                "currency":      { "type": "string", "description": "Currency code" }
            },
            "required": ["name", "target_amount", "currency"]
        }
    },
]


# ── Tool functions (what actually runs) ───────────────────────────────────────
# These are called by the agent loop when Claude requests a tool.
# Every function takes the DB session and user_id for security —
# we never let Claude query data for other users.

def get_monthly_expenses(db: Session, user_id: str, month: str, category: str = None):
    # Parse "2026-04" into a start and end datetime for filtering
    start = datetime.strptime(month, "%Y-%m")
    # End = first day of next month
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)

    query = db.query(Expense).filter(
        Expense.user_id == user_id,
        Expense.date >= start,
        Expense.date < end
    )

    if category:
        query = query.filter(Expense.category == category)

    expenses = query.order_by(Expense.date.desc()).all()

    # Return plain dicts — Claude receives JSON, not SQLAlchemy objects
    return [
        {
            "id": str(e.id),
            "name": e.name,
            "amount": e.amount,
            "currency": e.currency,
            "converted_amount": e.converted_amount,
            "category": e.category.value if hasattr(e.category, 'value') else e.category,
            "date": e.date.strftime("%Y-%m-%d"),
            "note": e.note
        }
        for e in expenses
    ]


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


def get_budgets(db: Session, user_id: str):
    budgets = db.query(Budget).filter(Budget.user_id == user_id).all()
    return [
        {
            "category": b.category.value if hasattr(b.category, 'value') else b.category,
            "monthly_limit": b.monthly_limit,
            "currency": b.currency
        }
        for b in budgets
    ]


def get_savings_goals(db: Session, user_id: str):
    goals = db.query(SavingsGoal).filter(
        SavingsGoal.user_id == user_id,
        SavingsGoal.completed_at == None
    ).all()
    return [
        {
            "id": str(g.id),
            "name": g.name,
            "target_amount": g.target_amount,
            "current_amount": g.current_amount,
            "currency": g.currency,
            "target_date": g.target_date.strftime("%Y-%m-%d") if g.target_date else None
        }
        for g in goals
    ]


def get_income_entries(db: Session, user_id: str, months: int = 3):
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=months * 30)
    entries = db.query(Income).filter(
        Income.user_id == user_id,
        Income.date >= cutoff
    ).order_by(Income.date.desc()).all()

    return [
        {
            "id": str(i.id),
            "amount": i.amount,
            "currency": i.currency,
            "converted_amount": i.converted_amount,
            "frequency": i.frequency.value if hasattr(i.frequency, 'value') else i.frequency,
            "source": i.source,
            "date": i.date.strftime("%Y-%m-%d")
        }
        for i in entries
    ]


def create_expense(db: Session, user_id: str, name: str, amount: float,
                   category: str, date: str, currency: str):
    expense = Expense(
        user_id=user_id,
        name=name,
        amount=amount,
        currency=currency,
        exchange_rate=1.0,      # agent always logs in the user's currency for now
        converted_amount=amount,
        category=category,
        date=datetime.strptime(date, "%Y-%m-%d"),
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return {"success": True, "name": expense.name, "amount": expense.amount, "category": category}


def create_savings_goal(db: Session, user_id: str, name: str,
                        target_amount: float, currency: str):
    goal = SavingsGoal(
        user_id=user_id,
        name=name,
        target_amount=target_amount,
        current_amount=0.0,
        currency=currency,
        created_by="agent"   # marks it was created by the agent, not manually
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return {"success": True, "name": goal.name, "target_amount": goal.target_amount}


def create_income(db: Session, user_id: str, amount: float, currency: str,
                  frequency: str, date: str, source: str = None):
    entry = Income(
        user_id=user_id,
        amount=amount,
        currency=currency,
        exchange_rate=1.0,
        converted_amount=amount,
        frequency=frequency,
        source=source,
        date=datetime.strptime(date, "%Y-%m-%d"),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"success": True, "amount": entry.amount, "frequency": entry.frequency.value, "source": entry.source}


def delete_expense(db: Session, user_id: str, expense_id: str):
    from uuid import UUID
    expense = db.query(Expense).filter(
        Expense.id == UUID(expense_id),
        Expense.user_id == user_id
    ).first()
    if not expense:
        return {"success": False, "error": "Expense not found"}
    db.delete(expense)
    db.commit()
    return {"success": True, "deleted": expense.name}


def delete_subscription(db: Session, user_id: str, subscription_id: str):
    from uuid import UUID
    sub = db.query(Subscription).filter(
        Subscription.id == UUID(subscription_id),
        Subscription.user_id == user_id
    ).first()
    if not sub:
        return {"success": False, "error": "Subscription not found"}
    db.delete(sub)
    db.commit()
    return {"success": True, "deleted": sub.name}


def delete_savings_goal(db: Session, user_id: str, goal_id: str):
    from uuid import UUID
    goal = db.query(SavingsGoal).filter(
        SavingsGoal.id == UUID(goal_id),
        SavingsGoal.user_id == user_id
    ).first()
    if not goal:
        return {"success": False, "error": "Goal not found"}
    db.delete(goal)
    db.commit()
    return {"success": True, "deleted": goal.name}


# ── Dispatcher ────────────────────────────────────────────────────────────────
# When Claude says "call get_monthly_expenses with these args",
# this function maps the tool name to the right Python function.
# It's just a lookup — nothing clever.

def run_tool(tool_name: str, tool_input: dict, db: Session, user_id: str):
    if tool_name == "get_monthly_expenses":
        return get_monthly_expenses(db, user_id, **tool_input)
    elif tool_name == "get_subscriptions":
        return get_subscriptions(db, user_id)
    elif tool_name == "get_budgets":
        return get_budgets(db, user_id)
    elif tool_name == "get_savings_goals":
        return get_savings_goals(db, user_id)
    elif tool_name == "get_income_entries":
        return get_income_entries(db, user_id, **tool_input)
    elif tool_name == "create_expense":
        return create_expense(db, user_id, **tool_input)
    elif tool_name == "create_income":
        return create_income(db, user_id, **tool_input)
    elif tool_name == "create_savings_goal":
        return create_savings_goal(db, user_id, **tool_input)
    elif tool_name == "delete_expense":
        return delete_expense(db, user_id, **tool_input)
    elif tool_name == "delete_subscription":
        return delete_subscription(db, user_id, **tool_input)
    elif tool_name == "delete_savings_goal":
        return delete_savings_goal(db, user_id, **tool_input)
    else:
        return {"error": f"Unknown tool: {tool_name}"}