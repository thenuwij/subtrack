"""Shared free-trial rules for subscriptions, Gmail approval, and the agent."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import PaymentReminder, Subscription
from app.services.schedules import utc_naive

AUTO_TRIAL_NOTE = "Created automatically for this free trial."


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def active_trial(subscription: Subscription, now: datetime | None = None) -> bool:
    """True while the saved free-trial end date has not passed.

    ``amount`` stores the post-trial recurring price.  Keeping this rule in one
    place prevents the dashboard and assistant from counting that future price
    as money already being paid.
    """
    if not subscription.trial_ends_at:
        return False
    today = utc_naive(now or utcnow()).date()
    return utc_naive(subscription.trial_ends_at).date() >= today


def sync_trial_reminder(
    db: Session,
    subscription: Subscription,
    *,
    now: datetime | None = None,
) -> PaymentReminder | None:
    """Keep one automatic dashboard reminder aligned with a trial end date.

    User-created reminders are never rewritten.  Only reminders carrying the
    exact automatic note are managed here, so changing or removing a trial does
    not destroy a user's custom reminder setup.
    """
    automatic = db.query(PaymentReminder).filter(
        PaymentReminder.user_id == subscription.user_id,
        PaymentReminder.subscription_id == subscription.id,
        PaymentReminder.kind == "trial_end",
        PaymentReminder.note == AUTO_TRIAL_NOTE,
    ).order_by(PaymentReminder.created_at.asc()).all()

    target = utc_naive(subscription.trial_ends_at) if subscription.trial_ends_at else None
    if not target:
        for reminder in automatic:
            reminder.is_active = False
            reminder.updated_at = utcnow()
        return None

    current = next((item for item in automatic if item.is_active), None)
    if current is None and automatic:
        current = automatic[0]
    if current is None:
        current = PaymentReminder(
            id=uuid4(),
            user_id=subscription.user_id,
            subscription_id=subscription.id,
            kind="trial_end",
            days_before=7,
            target_date=target,
            note=AUTO_TRIAL_NOTE,
            is_active=True,
        )
        db.add(current)
    else:
        current.target_date = target
        current.days_before = 7
        current.is_active = True
        current.dismissed_for = None
        current.updated_at = utcnow()

    for extra in automatic:
        if extra is not current:
            extra.is_active = False
            extra.updated_at = utcnow()
    return current
