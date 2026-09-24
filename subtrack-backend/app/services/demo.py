from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import (
    BillingCycle,
    Category,
    ChangeKind,
    DemoSession,
    DetectedSubscription,
    DetectionStatus,
    PaymentReminder,
    Subscription,
    SubscriptionChange,
    UserPreference,
)

DEMO_MONTHLY_INCOME = 6500.0
PURGE_BATCH_SIZE = 50

DEMO_PAYMENTS: tuple[dict, ...] = (
    {"name": "Rent", "category": "housing", "amount": 550, "interval_unit": "week",
     "interval_count": 1, "due_in": 2, "spending_type": "essential"},
    {"name": "Origin Energy", "category": "utilities", "amount": 186.4, "interval_unit": "month",
     "interval_count": 3, "due_in": 12, "amount_type": "variable", "spending_type": "essential"},
    {"name": "Aussie Broadband", "category": "phone_internet", "amount": 79, "interval_unit": "month",
     "interval_count": 1, "due_in": 9, "spending_type": "essential"},
    {"name": "Telstra Mobile", "category": "phone_internet", "amount": 55, "interval_unit": "month",
     "interval_count": 1, "due_in": 13, "spending_type": "essential"},
    {"name": "Car insurance", "category": "insurance", "amount": 1148, "interval_unit": "year",
     "interval_count": 1, "due_in": 24, "spending_type": "essential"},
    {"name": "Netflix", "category": "streaming", "amount": 25.99, "interval_unit": "month",
     "interval_count": 1, "due_in": 5, "spending_type": "optional"},
    {"name": "Spotify", "category": "streaming", "amount": 13.99, "interval_unit": "month",
     "interval_count": 1, "due_in": 11},
    {"name": "Spotify Premium", "category": "streaming", "amount": 13.99, "interval_unit": "month",
     "interval_count": 1, "due_in": 11},
    {"name": "Disney+", "category": "streaming", "amount": 15.99, "interval_unit": "month",
     "interval_count": 1, "trial_in": 3},
    {"name": "ChatGPT Plus", "category": "software", "amount": 20, "currency": "USD",
     "interval_unit": "month", "interval_count": 1, "due_in": 7},
    {"name": "iCloud+", "category": "cloud", "amount": 4.49, "interval_unit": "month",
     "interval_count": 1, "due_in": 21},
    {"name": "Anytime Fitness", "category": "fitness", "amount": 49.9, "interval_unit": "week",
     "interval_count": 2, "due_in": 4},
    {"name": "HelloFresh", "category": "food", "amount": 89.95, "interval_unit": "week",
     "interval_count": 1, "due_in": 6, "status": "paused", "paused_until_in": 20},
)

DEMO_DETECTIONS: tuple[dict, ...] = (
    {"merchant": "Adobe Creative Cloud", "sender_domain": "adobe.com", "category": Category.software,
     "amount": 32.99, "due_in": 16, "charge_count": 3},
    {"merchant": "Uber One", "sender_domain": "uber.com", "category": Category.memberships,
     "amount": 9.99, "due_in": 8, "charge_count": 2},
    {"merchant": "Stan", "sender_domain": "stan.com.au", "category": Category.streaming,
     "amount": 17, "previous_amount": 12, "due_in": 12, "charge_count": 3},
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _calendar_day(days_from_today: int) -> datetime:
    today = _utcnow().date() + timedelta(days=days_from_today)
    return datetime(today.year, today.month, today.day, 12)


def _demo_subscription(db: Session, user_id: str, spec: dict) -> Subscription:
    from app.routers.rates import conversion_for_storage
    from app.routers.subscriptions import resolve_split
    from app.services.recurrence import legacy_cycle_for

    unit, count = spec["interval_unit"], spec["interval_count"]
    status = spec.get("status", "active")
    trial_end = _calendar_day(spec["trial_in"]) if "trial_in" in spec else None
    next_due = _calendar_day(spec["due_in"]) if "due_in" in spec else trial_end
    currency = spec.get("currency", "AUD")
    split = resolve_split(spec["amount"])
    converted, exchange_rate, _quality = conversion_for_storage(
        split.amount, currency, "AUD", db,
    )
    return Subscription(
        id=uuid4(),
        user_id=user_id,
        name=spec["name"],
        category=Category(spec["category"]),
        amount=split.amount,
        full_amount=split.full_amount,
        share_ratio=split.share_ratio,
        split_mode=split.split_mode,
        currency=currency,
        converted_amount=converted,
        exchange_rate=exchange_rate,
        cycle=legacy_cycle_for(unit, count),
        interval_unit=unit,
        interval_count=count,
        next_due=next_due,
        trial_ends_at=trial_end,
        status=status,
        paused_until=(
            _calendar_day(spec["paused_until_in"]) if "paused_until_in" in spec else None
        ),
        amount_type=spec.get("amount_type", "fixed"),
        spending_type=spec.get("spending_type", "unspecified"),
        is_active=status not in {"cancelled", "ended"},
    )


def seed_demo_user(db: Session, user_id: str) -> None:
    from app.services.recurrence import monthly_equivalent
    from app.services.trials import AUTO_TRIAL_NOTE

    now = _utcnow()
    db.add(UserPreference(
        user_id=user_id,
        base_currency="AUD",
        monthly_income=DEMO_MONTHLY_INCOME,
    ))

    subs = {spec["name"]: _demo_subscription(db, user_id, spec) for spec in DEMO_PAYMENTS}
    broadband = subs["Aussie Broadband"]
    previous_broadband = monthly_equivalent(broadband.amount, broadband)
    broadband.amount = 89
    broadband.converted_amount = 89
    rows: list = list(subs.values())

    chatgpt = subs["ChatGPT Plus"]
    rows.extend([
        SubscriptionChange(
            user_id=user_id, subscription_id=chatgpt.id, name=chatgpt.name,
            kind=ChangeKind.added, old_monthly=None,
            new_monthly=monthly_equivalent(chatgpt.amount, chatgpt),
            currency=chatgpt.currency, changed_at=now - timedelta(days=4),
        ),
        SubscriptionChange(
            user_id=user_id, subscription_id=broadband.id, name=broadband.name,
            kind=ChangeKind.price_change, old_monthly=previous_broadband,
            new_monthly=monthly_equivalent(broadband.amount, broadband),
            currency="AUD", changed_at=now - timedelta(days=8),
        ),
        SubscriptionChange(
            user_id=user_id, subscription_id=uuid4(), name="Kayo Sports",
            kind=ChangeKind.removed, old_monthly=30, new_monthly=None,
            currency="AUD", changed_at=now - timedelta(days=13),
        ),
    ])

    trial = subs["Disney+"]
    rows.extend([
        PaymentReminder(
            id=uuid4(), user_id=user_id, subscription_id=trial.id, kind="trial_end",
            days_before=7, target_date=trial.trial_ends_at, note=AUTO_TRIAL_NOTE,
            is_active=True,
        ),
        PaymentReminder(
            user_id=user_id, subscription_id=subs["Car insurance"].id, kind="renewal",
            days_before=30, note="Compare quotes before it renews",
        ),
    ])

    for spec in DEMO_DETECTIONS:
        rows.append(DetectedSubscription(
            user_id=user_id,
            merchant=spec["merchant"],
            sender_domain=spec["sender_domain"],
            product_key=spec["merchant"].lower().replace(" ", "-"),
            category=spec["category"],
            cycle=BillingCycle.monthly,
            interval_unit="month",
            interval_count=1,
            cadence_confidence="high",
            cadence_evidence="Receipts arrive on the same day each month.",
            next_due=_calendar_day(spec["due_in"]),
            due_date_confidence="medium",
            due_date_evidence="Projected from the latest receipt.",
            amount=spec["amount"],
            previous_amount=spec.get("previous_amount"),
            currency="AUD",
            confidence="high",
            charge_count=spec["charge_count"],
            status=DetectionStatus.pending,
        ))

    db.add_all(rows)
    db.commit()


def purge_expired_demos(db: Session) -> int:
    from app.routers.account import _delete_owned_rows

    expired = (
        db.query(DemoSession)
        .filter(DemoSession.expires_at < _utcnow())
        .order_by(DemoSession.expires_at)
        .limit(PURGE_BATCH_SIZE)
        .all()
    )
    for session in expired:
        _delete_owned_rows(db, session.demo_user_id)
        db.delete(session)
    db.commit()
    return len(expired)
