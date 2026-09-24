from datetime import datetime, timedelta, timezone
from uuid import UUID

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
     "interval_count": 3, "due_in": 19, "amount_type": "variable", "spending_type": "essential"},
    {"name": "Aussie Broadband", "category": "phone_internet", "amount": 79, "interval_unit": "month",
     "interval_count": 1, "due_in": 9, "spending_type": "essential"},
    {"name": "Telstra Mobile", "category": "phone_internet", "amount": 55, "interval_unit": "month",
     "interval_count": 1, "due_in": 14, "spending_type": "essential"},
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


def seed_demo_user(db: Session, user_id: str) -> None:
    from app.routers.subscriptions import (
        SubscriptionCreate,
        SubscriptionUpdate,
        create_subscription,
        delete_subscription,
        update_subscription,
    )

    db.add(UserPreference(
        user_id=user_id,
        base_currency="AUD",
        monthly_income=DEMO_MONTHLY_INCOME,
    ))
    db.commit()

    created: dict[str, UUID] = {}
    for spec in DEMO_PAYMENTS:
        fields = {
            key: value for key, value in spec.items()
            if key not in {"due_in", "trial_in", "paused_until_in"}
        }
        if "due_in" in spec:
            fields["next_due"] = _calendar_day(spec["due_in"])
        if "trial_in" in spec:
            fields["trial_ends_at"] = _calendar_day(spec["trial_in"])
        if "paused_until_in" in spec:
            fields["paused_until"] = _calendar_day(spec["paused_until_in"])
        payload = create_subscription(SubscriptionCreate(**fields), user_id=user_id, db=db)
        created[spec["name"]] = UUID(payload["id"])

    update_subscription(
        created["Aussie Broadband"], SubscriptionUpdate(amount=89), user_id=user_id, db=db,
    )
    removed = create_subscription(
        SubscriptionCreate(
            name="Kayo Sports", category="streaming", amount=30,
            interval_unit="month", interval_count=1, next_due=_calendar_day(10),
        ),
        user_id=user_id,
        db=db,
    )
    delete_subscription(UUID(removed["id"]), user_id=user_id, db=db)

    changes = db.query(SubscriptionChange).filter(SubscriptionChange.user_id == user_id).all()
    for change in changes:
        if change.kind == ChangeKind.added and change.name != "ChatGPT Plus":
            db.delete(change)
        elif change.kind == ChangeKind.added:
            change.changed_at = _utcnow() - timedelta(days=4)
        elif change.kind == ChangeKind.price_change:
            change.changed_at = _utcnow() - timedelta(days=8)
        elif change.kind == ChangeKind.removed:
            change.changed_at = _utcnow() - timedelta(days=13)

    insurance = db.query(Subscription).filter(
        Subscription.user_id == user_id, Subscription.name == "Car insurance",
    ).one()
    db.add(PaymentReminder(
        user_id=user_id, subscription_id=insurance.id, kind="renewal", days_before=30,
        note="Compare quotes before it renews",
    ))

    for spec in DEMO_DETECTIONS:
        db.add(DetectedSubscription(
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
