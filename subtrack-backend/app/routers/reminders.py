"""Authenticated CRUD for in-app recurring-payment reminders."""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import verify_token
from app.models import PaymentReminder
from app.services.reminders import (
    get_owned_subscription,
    list_user_reminders,
    reminder_occurrence,
    reminder_payload,
    utcnow,
)
from app.services.recurrence import effective_status
from app.services.schedules import utc_naive


router = APIRouter(prefix="/reminders", tags=["reminders"])
ReminderKind = Literal["cancel", "renewal", "trial_end"]


class ReminderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription_id: UUID
    kind: ReminderKind
    days_before: int = Field(default=7, ge=0, le=365)
    target_date: Optional[datetime] = None
    note: Optional[str] = Field(default=None, max_length=300)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: Optional[str]) -> Optional[str]:
        cleaned = value.strip() if value else None
        return cleaned or None


class ReminderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Optional[ReminderKind] = None
    days_before: Optional[int] = Field(default=None, ge=0, le=365)
    target_date: Optional[datetime] = None
    note: Optional[str] = Field(default=None, max_length=300)
    is_active: Optional[bool] = None

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: Optional[str]) -> Optional[str]:
        cleaned = value.strip() if value else None
        return cleaned or None


def _get_reminder(db: Session, user_id: str, reminder_id: UUID) -> PaymentReminder:
    reminder = db.query(PaymentReminder).filter(
        PaymentReminder.id == reminder_id,
        PaymentReminder.user_id == user_id,
    ).first()
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return reminder


def _validate_schedule(kind: str, target_date: datetime | None, subscription) -> datetime | None:
    target = utc_naive(target_date) if target_date else None
    lifecycle = effective_status(subscription)
    if lifecycle in {"cancelled", "ended"}:
        raise HTTPException(
            status_code=422,
            detail="Cancelled or ended payments cannot have active reminders",
        )
    if kind == "trial_end" and target is None:
        raise HTTPException(status_code=422, detail="A trial reminder needs the trial end date")
    if target is None and subscription.next_due is None:
        raise HTTPException(
            status_code=422,
            detail="Add a next payment date before creating a recurring reminder",
        )
    if target is None and lifecycle == "paused" and not subscription.paused_until:
        raise HTTPException(
            status_code=422,
            detail="Add a resume date or choose a fixed reminder date for this paused payment",
        )
    if target and target.date() < utcnow().date():
        raise HTTPException(status_code=422, detail="The reminder date has already passed")
    return target


@router.get("")
def get_reminders(
    subscription_id: Optional[UUID] = None,
    include_inactive: bool = False,
    include_dismissed: bool = False,
    horizon_days: int = Query(default=365, ge=1, le=730),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    return list_user_reminders(
        db,
        user_id,
        subscription_id=subscription_id,
        include_inactive=include_inactive,
        include_dismissed=include_dismissed,
        horizon_days=horizon_days,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_reminder(
    data: ReminderCreate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    # Serialize reminder creation for one payment. Without this lock, two tabs
    # can both pass the duplicate check before either insert commits.
    subscription = get_owned_subscription(
        db,
        user_id,
        data.subscription_id,
        for_update=True,
    )
    if not subscription:
        raise HTTPException(status_code=404, detail="Recurring payment not found")
    target = _validate_schedule(data.kind, data.target_date, subscription)
    duplicate = db.query(PaymentReminder).filter(
        PaymentReminder.user_id == user_id,
        PaymentReminder.subscription_id == subscription.id,
        PaymentReminder.kind == data.kind,
        PaymentReminder.days_before == data.days_before,
        PaymentReminder.target_date == target,
        PaymentReminder.is_active == True,  # noqa: E712
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="That reminder already exists")

    reminder = PaymentReminder(
        id=uuid4(),
        user_id=user_id,
        subscription_id=subscription.id,
        kind=data.kind,
        days_before=data.days_before,
        target_date=target,
        note=data.note,
        is_active=True,
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder_payload(reminder, subscription, utcnow())


@router.patch("/{reminder_id}")
def update_reminder(
    reminder_id: UUID,
    data: ReminderUpdate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    reminder = _get_reminder(db, user_id, reminder_id)
    subscription = get_owned_subscription(db, user_id, reminder.subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="Recurring payment not found")
    fields = data.model_dump(exclude_unset=True)
    kind = fields.get("kind", reminder.kind)
    target = fields.get("target_date", reminder.target_date)
    fields["target_date"] = _validate_schedule(kind, target, subscription)
    days_before = fields.get("days_before", reminder.days_before)
    active = fields.get("is_active", reminder.is_active)
    if active:
        duplicate = db.query(PaymentReminder).filter(
            PaymentReminder.id != reminder.id,
            PaymentReminder.user_id == user_id,
            PaymentReminder.subscription_id == subscription.id,
            PaymentReminder.kind == kind,
            PaymentReminder.days_before == days_before,
            PaymentReminder.target_date == fields["target_date"],
            PaymentReminder.is_active == True,  # noqa: E712
        ).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="That reminder already exists")
    for key, value in fields.items():
        setattr(reminder, key, value)
    reminder.dismissed_for = None
    reminder.updated_at = utcnow()
    db.commit()
    db.refresh(reminder)
    return reminder_payload(reminder, subscription, utcnow())


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reminder(
    reminder_id: UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    reminder = _get_reminder(db, user_id, reminder_id)
    db.delete(reminder)
    db.commit()


@router.post("/{reminder_id}/dismiss")
def dismiss_reminder(
    reminder_id: UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    reminder = _get_reminder(db, user_id, reminder_id)
    subscription = get_owned_subscription(db, user_id, reminder.subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="Recurring payment not found")
    target, _ = reminder_occurrence(reminder, subscription, utcnow())
    if not target:
        raise HTTPException(status_code=409, detail="This reminder has no scheduled date")
    reminder.dismissed_for = target
    reminder.updated_at = utcnow()
    db.commit()
    db.refresh(reminder)
    return reminder_payload(reminder, subscription, utcnow())


@router.post("/{reminder_id}/restore")
def restore_reminder(
    reminder_id: UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    reminder = _get_reminder(db, user_id, reminder_id)
    subscription = get_owned_subscription(db, user_id, reminder.subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="Recurring payment not found")
    reminder.dismissed_for = None
    reminder.updated_at = utcnow()
    db.commit()
    db.refresh(reminder)
    return reminder_payload(reminder, subscription, utcnow())
