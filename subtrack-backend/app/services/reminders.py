"""Reminder scheduling shared by the API, dashboard, and assistant."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import PaymentReminder, Subscription
from app.services.schedules import project_next_occurrence, utc_naive


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso_utc(value: datetime | None) -> str | None:
    return f"{value.isoformat()}Z" if value else None


def reminder_occurrence(
    reminder: PaymentReminder,
    subscription: Subscription,
    now: datetime,
) -> tuple[datetime | None, str]:
    if reminder.target_date:
        return utc_naive(reminder.target_date), "fixed_date"
    return project_next_occurrence(subscription.next_due, subscription.cycle, now)


def reminder_payload(
    reminder: PaymentReminder,
    subscription: Subscription,
    now: datetime,
) -> dict:
    now = utc_naive(now)
    target, date_source = reminder_occurrence(reminder, subscription, now)
    alert_at = target - timedelta(days=reminder.days_before) if target else None
    dismissed = bool(
        target
        and reminder.dismissed_for
        and utc_naive(reminder.dismissed_for) == target
    )
    if not target:
        state = "needs_date"
    elif dismissed:
        state = "dismissed"
    elif target.date() < now.date():
        state = "overdue"
    elif alert_at and alert_at.date() <= now.date():
        state = "due"
    else:
        state = "upcoming"
    return {
        "id": str(reminder.id),
        "subscription_id": str(subscription.id),
        "subscription_name": subscription.name,
        "kind": reminder.kind,
        "days_before": reminder.days_before,
        "target_at": iso_utc(target),
        "alert_at": iso_utc(alert_at),
        "date_source": date_source,
        "status": state,
        "days_until_target": (target.date() - now.date()).days if target else None,
        "days_until_alert": (alert_at.date() - now.date()).days if alert_at else None,
        "note": reminder.note,
        "is_active": reminder.is_active,
        "created_at": iso_utc(reminder.created_at),
        "updated_at": iso_utc(reminder.updated_at),
    }


def get_owned_subscription(
    db: Session,
    user_id: str,
    subscription_id: UUID,
    *,
    active_only: bool = True,
) -> Subscription | None:
    query = db.query(Subscription).filter(
        Subscription.id == subscription_id,
        Subscription.user_id == user_id,
    )
    if active_only:
        query = query.filter(Subscription.is_active == True)  # noqa: E712
    return query.first()


def list_user_reminders(
    db: Session,
    user_id: str,
    *,
    subscription_id: UUID | None = None,
    reminder_ids: list[UUID] | None = None,
    include_inactive: bool = False,
    include_dismissed: bool = False,
    horizon_days: int = 365,
    now: datetime | None = None,
) -> list[dict]:
    now = utc_naive(now or utcnow())
    query = db.query(PaymentReminder).filter(PaymentReminder.user_id == user_id)
    if not include_inactive:
        query = query.filter(PaymentReminder.is_active == True)  # noqa: E712
    if subscription_id:
        query = query.filter(PaymentReminder.subscription_id == subscription_id)
    if reminder_ids:
        query = query.filter(PaymentReminder.id.in_(reminder_ids))
    reminders = query.order_by(PaymentReminder.created_at.desc()).limit(200).all()
    subscription_ids = {reminder.subscription_id for reminder in reminders}
    subscriptions = {
        sub.id: sub for sub in db.query(Subscription).filter(
            Subscription.user_id == user_id,
            Subscription.id.in_(subscription_ids),
            Subscription.is_active == True,  # noqa: E712
        ).all()
    } if subscription_ids else {}

    payloads = []
    horizon = now.date() + timedelta(days=max(1, min(horizon_days, 730)))
    for reminder in reminders:
        subscription = subscriptions.get(reminder.subscription_id)
        if not subscription:
            continue
        payload = reminder_payload(reminder, subscription, now)
        if not include_dismissed and payload["status"] == "dismissed":
            continue
        target = datetime.fromisoformat(payload["target_at"].removesuffix("Z")) \
            if payload["target_at"] else None
        if target and target.date() > horizon:
            continue
        payloads.append(payload)

    priority = {"overdue": 0, "due": 1, "upcoming": 2, "needs_date": 3, "dismissed": 4}
    payloads.sort(key=lambda item: (
        priority.get(item["status"], 9),
        item["target_at"] or "9999",
        item["subscription_name"].casefold(),
    ))
    return payloads
