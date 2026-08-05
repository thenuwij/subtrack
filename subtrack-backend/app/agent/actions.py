"""Persistent, user-confirmed mutations for the Subtrack assistant.

The language model may create an inert proposal, never a mutation.  Confirming
is a separate authenticated request that locks the proposal, checks ownership,
verifies that referenced records have not changed, and applies the operation in
the same database transaction as the completed action status.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AgentAction,
    AgentMessage,
    BillingCycle,
    Category,
    ChangeKind,
    DetectedSubscription,
    DetectionStatus,
    PaymentReminder,
    Subscription,
    SubscriptionChange,
    UserPreference,
)
from app.routers.subscriptions import (
    log_change,
    monthly_equivalent,
    rebill,
    resolve_split,
    retarget_detection_links,
)
from app.services.reminders import reminder_occurrence
from app.services.schedules import utc_naive
from app.services.trials import sync_trial_reminder


ACTION_EXPIRES_AFTER = timedelta(hours=24)
ACTION_TOOL_PREFIX = "propose_"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    return f"{utc_naive(value).isoformat()}Z" if value else None


def _enum(value):
    return value.value if hasattr(value, "value") else value


class StrictAction(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AddPayment(StrictAction):
    name: str = Field(min_length=1, max_length=160)
    category: Category
    amount: float = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    cycle: BillingCycle
    next_due: datetime | None = None
    trial_ends_at: datetime | None = None


class UpdatePayment(StrictAction):
    subscription_id: UUID
    name: str | None = Field(default=None, min_length=1, max_length=160)
    category: Category | None = None
    amount: float | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    cycle: BillingCycle | None = None
    next_due: datetime | None = None

    @model_validator(mode="after")
    def has_change(self):
        values = self.model_dump(exclude={"subscription_id"})
        if not any(value is not None for value in values.values()):
            raise ValueError("At least one field must be changed")
        return self


class RemovePayment(StrictAction):
    subscription_id: UUID


class MergePayments(StrictAction):
    source_subscription_id: UUID
    target_subscription_id: UUID

    @model_validator(mode="after")
    def different_records(self):
        if self.source_subscription_id == self.target_subscription_id:
            raise ValueError("A payment cannot be merged into itself")
        return self


class AddReminder(StrictAction):
    subscription_id: UUID
    kind: Literal["cancel", "renewal", "trial_end"]
    days_before: int = Field(default=7, ge=0, le=365)
    target_date: datetime | None = None
    note: str | None = Field(default=None, max_length=300)


class MarkTrial(StrictAction):
    subscription_id: UUID
    trial_ends_at: datetime
    price_after_trial: float | None = Field(default=None, gt=0)


class ApproveDetection(StrictAction):
    detection_id: UUID
    amount: float | None = Field(default=None, gt=0)
    duplicate_resolution: Literal["keep_both", "replace_existing"] | None = None


class DismissDetection(StrictAction):
    detection_id: UUID


class DismissReminder(StrictAction):
    reminder_id: UUID


ACTION_MODELS: dict[str, type[StrictAction]] = {
    "propose_add_recurring_payment": AddPayment,
    "propose_update_recurring_payment": UpdatePayment,
    "propose_remove_recurring_payment": RemovePayment,
    "propose_merge_recurring_payments": MergePayments,
    "propose_add_payment_reminder": AddReminder,
    "propose_mark_payment_as_free_trial": MarkTrial,
    "propose_approve_inbox_detection": ApproveDetection,
    "propose_dismiss_inbox_detection": DismissDetection,
    "propose_dismiss_payment_reminder": DismissReminder,
}


ACTION_TOOL_DEFINITIONS = [
    {
        "name": "propose_add_recurring_payment",
        "description": (
            "Prepare an add-payment action for explicit user confirmation. Nothing is added "
            "until the user presses Confirm. For a free trial, amount is the price after the "
            "trial and trial_ends_at is required."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 160},
                "category": {"type": "string", "enum": [item.value for item in Category]},
                "amount": {"type": "number", "exclusiveMinimum": 0},
                "currency": {"type": "string", "minLength": 3, "maxLength": 3},
                "cycle": {"type": "string", "enum": [item.value for item in BillingCycle]},
                "next_due": {"type": ["string", "null"], "format": "date-time"},
                "trial_ends_at": {"type": ["string", "null"], "format": "date-time"},
            },
            "required": ["name", "category", "amount", "currency", "cycle", "next_due", "trial_ends_at"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_update_recurring_payment",
        "description": "Prepare changes to one tracked recurring payment. The user must confirm before data changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subscription_id": {"type": "string", "format": "uuid"},
                "name": {"type": ["string", "null"], "maxLength": 160},
                "category": {"type": ["string", "null"], "enum": [item.value for item in Category] + [None]},
                "amount": {"type": ["number", "null"], "exclusiveMinimum": 0},
                "currency": {"type": ["string", "null"], "minLength": 3, "maxLength": 3},
                "cycle": {"type": ["string", "null"], "enum": [item.value for item in BillingCycle] + [None]},
                "next_due": {"type": ["string", "null"], "format": "date-time"},
            },
            "required": ["subscription_id", "name", "category", "amount", "currency", "cycle", "next_due"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_remove_recurring_payment",
        "description": (
            "Prepare removal of a payment from Subtrack. This does not cancel the service "
            "with the merchant; make that limitation explicit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"subscription_id": {"type": "string", "format": "uuid"}},
            "required": ["subscription_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_merge_recurring_payments",
        "description": (
            "Prepare merging a duplicate record into the payment the user wants to keep. "
            "Only use after read tools provide both owned IDs and the user has identified the duplicate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_subscription_id": {"type": "string", "format": "uuid"},
                "target_subscription_id": {"type": "string", "format": "uuid"},
            },
            "required": ["source_subscription_id", "target_subscription_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_add_payment_reminder",
        "description": (
            "Prepare an in-app dashboard reminder. Use trial_end for a free-trial deadline; "
            "email and push delivery are not available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subscription_id": {"type": "string", "format": "uuid"},
                "kind": {"type": "string", "enum": ["cancel", "renewal", "trial_end"]},
                "days_before": {"type": "integer", "minimum": 0, "maximum": 365},
                "target_date": {"type": ["string", "null"], "format": "date-time"},
                "note": {"type": ["string", "null"], "maxLength": 300},
            },
            "required": ["subscription_id", "kind", "days_before", "target_date", "note"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_mark_payment_as_free_trial",
        "description": (
            "Prepare marking an existing payment as a free trial. Confirmation saves the trial "
            "end as its first due date and automatically creates a 7-day dashboard reminder."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subscription_id": {"type": "string", "format": "uuid"},
                "trial_ends_at": {"type": "string", "format": "date-time"},
                "price_after_trial": {"type": ["number", "null"], "exclusiveMinimum": 0},
            },
            "required": ["subscription_id", "trial_ends_at", "price_after_trial"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_approve_inbox_detection",
        "description": (
            "Prepare approval of one pending Gmail detection. Use amount when a detected free "
            "trial did not state its future recurring price."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "detection_id": {"type": "string", "format": "uuid"},
                "amount": {"type": ["number", "null"], "exclusiveMinimum": 0},
                "duplicate_resolution": {
                    "type": ["string", "null"],
                    "enum": ["keep_both", "replace_existing", None],
                },
            },
            "required": ["detection_id", "amount", "duplicate_resolution"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_dismiss_inbox_detection",
        "description": "Prepare dismissal of one pending Gmail detection after the user asks for it.",
        "input_schema": {
            "type": "object",
            "properties": {"detection_id": {"type": "string", "format": "uuid"}},
            "required": ["detection_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_dismiss_payment_reminder",
        "description": "Prepare dismissal of one visible reminder occurrence. Recurring reminders return next cycle.",
        "input_schema": {
            "type": "object",
            "properties": {"reminder_id": {"type": "string", "format": "uuid"}},
            "required": ["reminder_id"],
            "additionalProperties": False,
        },
    },
]


def _owned_subscription(db: Session, user_id: str, identifier: UUID) -> Subscription:
    row = db.query(Subscription).filter(
        Subscription.id == identifier,
        Subscription.user_id == user_id,
        Subscription.is_active == True,  # noqa: E712
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Recurring payment not found")
    return row


def _owned_detection(db: Session, user_id: str, identifier: UUID) -> DetectedSubscription:
    row = db.query(DetectedSubscription).filter(
        DetectedSubscription.id == identifier,
        DetectedSubscription.user_id == user_id,
        DetectedSubscription.status == DetectionStatus.pending,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Pending inbox detection not found")
    return row


def _owned_reminder(db: Session, user_id: str, identifier: UUID) -> PaymentReminder:
    row = db.query(PaymentReminder).filter(
        PaymentReminder.id == identifier,
        PaymentReminder.user_id == user_id,
        PaymentReminder.is_active == True,  # noqa: E712
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Active reminder not found")
    return row


def _subscription_snapshot(row: Subscription) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "amount": row.amount,
        "currency": row.currency,
        "cycle": _enum(row.cycle),
        "category": _enum(row.category),
        "next_due": _iso(row.next_due),
        "trial_ends_at": _iso(row.trial_ends_at),
        "is_active": bool(row.is_active),
    }


def _detection_snapshot(row: DetectedSubscription) -> dict:
    return {
        "id": str(row.id),
        "merchant": row.merchant,
        "amount": row.amount,
        "currency": row.currency,
        "cycle": _enum(row.cycle),
        "trial_ends_at": _iso(row.trial_ends_at),
        "status": _enum(row.status),
    }


def _reminder_snapshot(row: PaymentReminder) -> dict:
    return {
        "id": str(row.id),
        "subscription_id": str(row.subscription_id),
        "kind": row.kind,
        "days_before": row.days_before,
        "target_date": _iso(row.target_date),
        "dismissed_for": _iso(row.dismissed_for),
        "is_active": bool(row.is_active),
    }


def _proposal_copy(tool_name: str, data: StrictAction, db: Session, user_id: str):
    payload = data.model_dump(mode="json", exclude_unset=False)
    expected = None

    if tool_name == "propose_add_recurring_payment":
        item = data
        assert isinstance(item, AddPayment)
        if item.trial_ends_at and utc_naive(item.trial_ends_at).date() < utcnow().date():
            raise HTTPException(status_code=422, detail="The trial end date has already passed")
        summary = f"Add {item.name}"
        description = f"Track {item.currency.upper()} {item.amount:.2f} per {item.cycle.value}."
        if item.trial_ends_at:
            description += f" Free trial ends {_iso(item.trial_ends_at)[:10]}; a 7-day dashboard reminder will be added."
    elif tool_name == "propose_update_recurring_payment":
        item = data
        assert isinstance(item, UpdatePayment)
        sub = _owned_subscription(db, user_id, item.subscription_id)
        expected = {"subscription": _subscription_snapshot(sub)}
        summary = f"Update {sub.name}"
        changed = [
            key.replace("_", " ")
            for key, value in item.model_dump(exclude={"subscription_id"}).items()
            if value is not None
        ]
        description = f"Change {', '.join(changed)} after confirmation."
    elif tool_name == "propose_remove_recurring_payment":
        item = data
        assert isinstance(item, RemovePayment)
        sub = _owned_subscription(db, user_id, item.subscription_id)
        expected = {"subscription": _subscription_snapshot(sub)}
        summary = f"Remove {sub.name} from Subtrack"
        description = "Deletes this tracked record and its reminders. It does not cancel the service with the merchant."
    elif tool_name == "propose_merge_recurring_payments":
        item = data
        assert isinstance(item, MergePayments)
        source = _owned_subscription(db, user_id, item.source_subscription_id)
        target = _owned_subscription(db, user_id, item.target_subscription_id)
        expected = {
            "source": _subscription_snapshot(source),
            "target": _subscription_snapshot(target),
        }
        summary = f"Merge {source.name} into {target.name}"
        description = f"Keep {target.name}, move history and reminders to it, and remove the duplicate {source.name} record."
    elif tool_name == "propose_add_payment_reminder":
        item = data
        assert isinstance(item, AddReminder)
        sub = _owned_subscription(db, user_id, item.subscription_id)
        target = item.target_date or (sub.trial_ends_at if item.kind == "trial_end" else sub.next_due)
        if not target:
            raise HTTPException(status_code=422, detail="This reminder needs a saved date")
        if utc_naive(target).date() < utcnow().date():
            raise HTTPException(status_code=422, detail="The reminder date has already passed")
        payload["target_date"] = _iso(target)
        expected = {"subscription": _subscription_snapshot(sub)}
        summary = f"Remind you about {sub.name}"
        description = f"Show an in-app {item.kind.replace('_', ' ')} reminder {item.days_before} days before {_iso(target)[:10]}."
    elif tool_name == "propose_mark_payment_as_free_trial":
        item = data
        assert isinstance(item, MarkTrial)
        sub = _owned_subscription(db, user_id, item.subscription_id)
        if utc_naive(item.trial_ends_at).date() < utcnow().date():
            raise HTTPException(status_code=422, detail="The trial end date has already passed")
        expected = {"subscription": _subscription_snapshot(sub)}
        summary = f"Mark {sub.name} as a free trial"
        description = f"Trial ends {_iso(item.trial_ends_at)[:10]}; save it as the next due date and add a 7-day dashboard reminder."
    elif tool_name == "propose_approve_inbox_detection":
        item = data
        assert isinstance(item, ApproveDetection)
        detection = _owned_detection(db, user_id, item.detection_id)
        amount = item.amount if item.amount is not None else detection.amount
        if amount is None or amount <= 0:
            raise HTTPException(status_code=422, detail="The price after this trial is needed before approval")
        expected = {"detection": _detection_snapshot(detection)}
        if detection.existing_subscription_id:
            tracked = _owned_subscription(db, user_id, detection.existing_subscription_id)
            expected["subscription"] = _subscription_snapshot(tracked)
        elif detection.similar_subscription_id:
            if item.duplicate_resolution is None:
                raise HTTPException(
                    status_code=422,
                    detail="This may duplicate an existing payment. Ask whether to replace it or keep both.",
                )
            # Keeping both does not depend on the suggested row still existing.
            # Replacing it does, so snapshot that target for the confirmation
            # transaction and fail safely if it changes in the meantime.
            if item.duplicate_resolution == "replace_existing":
                similar = _owned_subscription(db, user_id, detection.similar_subscription_id)
                expected["subscription"] = _subscription_snapshot(similar)
        summary = f"Approve {detection.merchant}"
        description = f"Add or update this reviewed inbox finding at {detection.currency} {amount:.2f} per {_enum(detection.cycle)}."
        if detection.trial_ends_at:
            description += " Its trial end and automatic dashboard reminder will also be saved."
    elif tool_name == "propose_dismiss_inbox_detection":
        item = data
        assert isinstance(item, DismissDetection)
        detection = _owned_detection(db, user_id, item.detection_id)
        expected = {"detection": _detection_snapshot(detection)}
        summary = f"Dismiss {detection.merchant}"
        description = "Remove this finding from the review queue and keep it out of future scan suggestions."
    elif tool_name == "propose_dismiss_payment_reminder":
        item = data
        assert isinstance(item, DismissReminder)
        reminder = _owned_reminder(db, user_id, item.reminder_id)
        sub = _owned_subscription(db, user_id, reminder.subscription_id)
        expected = {
            "reminder": _reminder_snapshot(reminder),
            "subscription": _subscription_snapshot(sub),
        }
        summary = f"Dismiss reminder for {sub.name}"
        description = "Dismiss this occurrence. If it repeats, the reminder will return for the next billing cycle."
    else:
        raise HTTPException(status_code=400, detail="Unknown assistant action")
    return payload, expected, summary, description


def serialize_action(action: AgentAction) -> dict:
    return {
        "id": str(action.id),
        "thread_id": str(action.thread_id),
        "assistant_message_id": str(action.assistant_message_id),
        "action_type": action.action_type,
        "summary": action.summary,
        "description": action.description,
        "status": action.status,
        "result": action.result_json,
        "error_code": action.error_code,
        "error_message": action.error_message,
        "expires_at": _iso(action.expires_at),
        "created_at": _iso(action.created_at),
        "resolved_at": _iso(action.resolved_at),
    }


def create_action_proposal(
    tool_name: str,
    tool_input: dict,
    db: Session,
    user_id: str,
    *,
    thread_id: UUID,
    assistant_message_id: UUID,
) -> dict:
    model = ACTION_MODELS.get(tool_name)
    if not model:
        raise HTTPException(status_code=400, detail="Unknown assistant action")
    # Ensure a compromised caller cannot attach actions to another user's
    # conversation even if it learns a message UUID.
    message = db.query(AgentMessage).filter(
        AgentMessage.id == assistant_message_id,
        AgentMessage.thread_id == thread_id,
        AgentMessage.user_id == user_id,
        AgentMessage.role == "assistant",
    ).first()
    if not message:
        raise HTTPException(status_code=404, detail="Assistant message not found")

    parsed = model.model_validate(tool_input)
    payload, expected, summary, description = _proposal_copy(tool_name, parsed, db, user_id)
    fingerprint = hashlib.sha256(
        json.dumps({"tool": tool_name, "payload": payload}, sort_keys=True).encode()
    ).hexdigest()
    existing = db.query(AgentAction).filter(
        AgentAction.assistant_message_id == assistant_message_id,
        AgentAction.fingerprint == fingerprint,
    ).first()
    if existing:
        return serialize_action(existing)

    action = AgentAction(
        id=uuid4(),
        thread_id=thread_id,
        assistant_message_id=assistant_message_id,
        user_id=user_id,
        action_type=tool_name.removeprefix(ACTION_TOOL_PREFIX),
        payload_json=payload,
        expected_json=expected,
        summary=summary,
        description=description,
        fingerprint=fingerprint,
        status="pending",
        expires_at=utcnow() + ACTION_EXPIRES_AFTER,
    )
    db.add(action)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        action = db.query(AgentAction).filter(
            AgentAction.assistant_message_id == assistant_message_id,
            AgentAction.fingerprint == fingerprint,
        ).one()
    else:
        db.refresh(action)
    return serialize_action(action)


def actions_for_messages(
    db: Session,
    user_id: str,
    message_ids: list[UUID],
) -> dict[UUID, list[dict]]:
    if not message_ids:
        return {}
    rows = db.query(AgentAction).filter(
        AgentAction.user_id == user_id,
        AgentAction.assistant_message_id.in_(message_ids),
    ).order_by(AgentAction.created_at.asc()).all()
    grouped: dict[UUID, list[dict]] = {}
    now = utcnow()
    changed = False
    for row in rows:
        if row.status == "pending" and row.expires_at < now:
            row.status = "expired"
            row.resolved_at = now
            changed = True
        grouped.setdefault(row.assistant_message_id, []).append(serialize_action(row))
    if changed:
        db.commit()
    return grouped


def _assert_fresh(action: AgentAction, db: Session, user_id: str) -> None:
    expected = action.expected_json or {}
    if "subscription" in expected:
        sub = _owned_subscription(db, user_id, UUID(expected["subscription"]["id"]))
        current = _subscription_snapshot(sub)
        if current != expected["subscription"]:
            raise HTTPException(status_code=409, detail="This payment changed after the action was proposed. Ask the assistant again.")
    if "source" in expected:
        source = _owned_subscription(db, user_id, UUID(expected["source"]["id"]))
        target = _owned_subscription(db, user_id, UUID(expected["target"]["id"]))
        if _subscription_snapshot(source) != expected["source"] or _subscription_snapshot(target) != expected["target"]:
            raise HTTPException(status_code=409, detail="One of these payments changed after the merge was proposed.")
    if "detection" in expected:
        detection = _owned_detection(db, user_id, UUID(expected["detection"]["id"]))
        if _detection_snapshot(detection) != expected["detection"]:
            raise HTTPException(status_code=409, detail="This inbox finding changed after the action was proposed.")
    if "reminder" in expected:
        reminder = _owned_reminder(db, user_id, UUID(expected["reminder"]["id"]))
        if _reminder_snapshot(reminder) != expected["reminder"]:
            raise HTTPException(status_code=409, detail="This reminder changed after the action was proposed.")


def _execute_add_payment(action: AgentAction, db: Session, user_id: str) -> dict:
    data = AddPayment.model_validate(action.payload_json)
    trial_end = utc_naive(data.trial_ends_at) if data.trial_ends_at else None
    next_due = trial_end or (utc_naive(data.next_due) if data.next_due else None)
    preference = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    base = preference.base_currency if preference else "AUD"
    sub = Subscription(
        id=uuid4(), user_id=user_id, name=data.name.strip(), category=data.category,
        amount=data.amount, full_amount=None, share_ratio=1.0, split_mode="full",
        currency=data.currency.upper(), exchange_rate=1.0,
        converted_amount=data.amount if data.currency.upper() == base else None,
        cycle=data.cycle, next_due=next_due, trial_ends_at=trial_end, is_active=True,
    )
    db.add(sub)
    db.flush()
    if trial_end:
        sync_trial_reminder(db, sub)
    log_change(db, sub, ChangeKind.added, None, monthly_equivalent(sub.amount, sub.cycle))
    return {"subscription_id": str(sub.id), "name": sub.name}


def _execute_update_payment(action: AgentAction, db: Session, user_id: str) -> dict:
    data = UpdatePayment.model_validate(action.payload_json)
    sub = _owned_subscription(db, user_id, data.subscription_id)
    before = monthly_equivalent(sub.amount, sub.cycle)
    fields = data.model_dump(exclude_unset=True)
    fields.pop("subscription_id", None)
    for key, value in fields.items():
        if value is not None:
            if key == "currency":
                value = value.upper()
            elif key == "next_due":
                value = utc_naive(value)
            setattr(sub, key, value)
    if "currency" in fields or "amount" in fields:
        preference = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
        base = preference.base_currency if preference else "AUD"
        sub.converted_amount = sub.amount if sub.currency == base else None
    after = monthly_equivalent(sub.amount, sub.cycle)
    if after != before:
        log_change(db, sub, ChangeKind.price_change, before, after)
    return {"subscription_id": str(sub.id), "name": sub.name}


def _execute_remove_payment(action: AgentAction, db: Session, user_id: str) -> dict:
    data = RemovePayment.model_validate(action.payload_json)
    sub = _owned_subscription(db, user_id, data.subscription_id)
    name = sub.name
    log_change(db, sub, ChangeKind.removed, monthly_equivalent(sub.amount, sub.cycle), None)
    db.query(PaymentReminder).filter(
        PaymentReminder.user_id == user_id,
        PaymentReminder.subscription_id == sub.id,
    ).delete(synchronize_session=False)
    retarget_detection_links(db, user_id, sub.id, None)
    db.delete(sub)
    return {"subscription_id": str(data.subscription_id), "name": name, "merchant_cancelled": False}


def _execute_merge(action: AgentAction, db: Session, user_id: str) -> dict:
    data = MergePayments.model_validate(action.payload_json)
    source = _owned_subscription(db, user_id, data.source_subscription_id)
    target = _owned_subscription(db, user_id, data.target_subscription_id)
    if not target.source_key and source.source_key:
        target.source_key = source.source_key
        target.source_domain = source.source_domain
    if not target.trial_ends_at and source.trial_ends_at:
        target.trial_ends_at = source.trial_ends_at
        target.next_due = source.next_due or target.next_due
    db.query(SubscriptionChange).filter(
        SubscriptionChange.subscription_id == source.id,
    ).update({SubscriptionChange.subscription_id: target.id}, synchronize_session=False)
    existing_keys = {
        (item.kind, item.days_before, item.target_date)
        for item in db.query(PaymentReminder).filter(
            PaymentReminder.user_id == user_id,
            PaymentReminder.subscription_id == target.id,
            PaymentReminder.is_active == True,  # noqa: E712
        ).all()
    }
    for reminder in db.query(PaymentReminder).filter(
        PaymentReminder.user_id == user_id,
        PaymentReminder.subscription_id == source.id,
    ).all():
        key = (reminder.kind, reminder.days_before, reminder.target_date)
        if reminder.is_active and key in existing_keys:
            db.delete(reminder)
        else:
            reminder.subscription_id = target.id
            if reminder.is_active:
                existing_keys.add(key)
    retarget_detection_links(db, user_id, source.id, target.id)
    db.delete(source)
    return {"removed_subscription_id": str(source.id), "subscription_id": str(target.id), "name": target.name}


def _execute_add_reminder(action: AgentAction, db: Session, user_id: str) -> dict:
    data = AddReminder.model_validate(action.payload_json)
    sub = _owned_subscription(db, user_id, data.subscription_id)
    target = utc_naive(data.target_date) if data.target_date else None
    if not target:
        target = sub.trial_ends_at if data.kind == "trial_end" else sub.next_due
    if not target or utc_naive(target).date() < utcnow().date():
        raise HTTPException(status_code=422, detail="The reminder needs a future date")
    duplicate = db.query(PaymentReminder).filter(
        PaymentReminder.user_id == user_id,
        PaymentReminder.subscription_id == sub.id,
        PaymentReminder.kind == data.kind,
        PaymentReminder.days_before == data.days_before,
        PaymentReminder.target_date == utc_naive(target),
        PaymentReminder.is_active == True,  # noqa: E712
    ).first()
    if duplicate:
        return {"reminder_id": str(duplicate.id), "subscription_id": str(sub.id), "already_existed": True}
    reminder = PaymentReminder(
        id=uuid4(), user_id=user_id, subscription_id=sub.id, kind=data.kind,
        days_before=data.days_before, target_date=utc_naive(target),
        note=data.note.strip() if data.note else None, is_active=True,
    )
    db.add(reminder)
    db.flush()
    return {"reminder_id": str(reminder.id), "subscription_id": str(sub.id)}


def _execute_mark_trial(action: AgentAction, db: Session, user_id: str) -> dict:
    data = MarkTrial.model_validate(action.payload_json)
    sub = _owned_subscription(db, user_id, data.subscription_id)
    target = utc_naive(data.trial_ends_at)
    if target.date() < utcnow().date():
        raise HTTPException(status_code=422, detail="The trial end date has already passed")
    if data.price_after_trial is not None:
        before = monthly_equivalent(sub.amount, sub.cycle)
        sub.amount = data.price_after_trial
        preference = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
        base = preference.base_currency if preference else "AUD"
        sub.converted_amount = sub.amount if sub.currency == base else None
        after = monthly_equivalent(sub.amount, sub.cycle)
        if after != before:
            log_change(db, sub, ChangeKind.price_change, before, after)
    sub.trial_ends_at = target
    sub.next_due = target
    reminder = sync_trial_reminder(db, sub)
    db.flush()
    return {"subscription_id": str(sub.id), "reminder_id": str(reminder.id) if reminder else None}


def _execute_approve_detection(action: AgentAction, db: Session, user_id: str) -> dict:
    data = ApproveDetection.model_validate(action.payload_json)
    detection = _owned_detection(db, user_id, data.detection_id)
    billed = data.amount if data.amount is not None else detection.amount
    if billed <= 0:
        raise HTTPException(status_code=422, detail="The price after this trial is needed")
    split = resolve_split(billed)
    target_id = detection.existing_subscription_id
    if not target_id and data.duplicate_resolution == "replace_existing":
        target_id = detection.similar_subscription_id
    if target_id:
        sub = _owned_subscription(db, user_id, target_id)
        before = monthly_equivalent(sub.amount, sub.cycle)
        split = rebill(sub, billed)
        sub.amount, sub.full_amount = split.amount, split.full_amount
        sub.share_ratio, sub.split_mode = split.share_ratio, split.split_mode
        if detection.merchant and len(detection.merchant) > len(sub.name):
            sub.name = detection.merchant
        sub.category, sub.cycle, sub.currency = detection.category, detection.cycle, detection.currency
        preference = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
        base = preference.base_currency if preference else "AUD"
        sub.converted_amount = sub.amount if sub.currency == base else None
        sub.source_domain, sub.source_key = detection.sender_domain, detection.product_key or sub.source_key
        if detection.trial_ends_at:
            sub.trial_ends_at = detection.trial_ends_at
            sub.next_due = detection.trial_ends_at
            sync_trial_reminder(db, sub)
        elif sub.trial_ends_at and detection.charge_count > 0:
            sub.trial_ends_at = None
            sync_trial_reminder(db, sub)
        after = monthly_equivalent(sub.amount, sub.cycle)
        if after != before:
            log_change(db, sub, ChangeKind.price_change, before, after)
    else:
        preference = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
        base = preference.base_currency if preference else "AUD"
        sub = Subscription(
            id=uuid4(), user_id=user_id, name=detection.merchant,
            category=detection.category, amount=split.amount,
            full_amount=split.full_amount, share_ratio=split.share_ratio,
            split_mode=split.split_mode, source_domain=detection.sender_domain,
            source_key=detection.product_key or None, currency=detection.currency,
            exchange_rate=1.0,
            converted_amount=split.amount if detection.currency == base else None,
            cycle=detection.cycle, next_due=detection.trial_ends_at,
            trial_ends_at=detection.trial_ends_at, is_active=not detection.cancelled,
        )
        db.add(sub)
        db.flush()
        if sub.trial_ends_at and sub.is_active:
            sync_trial_reminder(db, sub)
        log_change(db, sub, ChangeKind.added, None, monthly_equivalent(sub.amount, sub.cycle))
    if detection.cancelled:
        sub.is_active = False
        db.query(PaymentReminder).filter(
            PaymentReminder.user_id == user_id,
            PaymentReminder.subscription_id == sub.id,
        ).update({PaymentReminder.is_active: False}, synchronize_session=False)
    detection.status = DetectionStatus.approved
    detection.resolved_at = utcnow()
    return {"detection_id": str(detection.id), "subscription_id": str(sub.id)}


def _execute_dismiss_detection(action: AgentAction, db: Session, user_id: str) -> dict:
    data = DismissDetection.model_validate(action.payload_json)
    detection = _owned_detection(db, user_id, data.detection_id)
    detection.status = DetectionStatus.dismissed
    detection.resolved_at = utcnow()
    return {"detection_id": str(detection.id)}


def _execute_dismiss_reminder(action: AgentAction, db: Session, user_id: str) -> dict:
    data = DismissReminder.model_validate(action.payload_json)
    reminder = _owned_reminder(db, user_id, data.reminder_id)
    sub = _owned_subscription(db, user_id, reminder.subscription_id)
    target, _ = reminder_occurrence(reminder, sub, utcnow())
    if not target:
        raise HTTPException(status_code=409, detail="This reminder has no scheduled date")
    reminder.dismissed_for = target
    reminder.updated_at = utcnow()
    return {"reminder_id": str(reminder.id), "subscription_id": str(sub.id)}


EXECUTORS = {
    "add_recurring_payment": _execute_add_payment,
    "update_recurring_payment": _execute_update_payment,
    "remove_recurring_payment": _execute_remove_payment,
    "merge_recurring_payments": _execute_merge,
    "add_payment_reminder": _execute_add_reminder,
    "mark_payment_as_free_trial": _execute_mark_trial,
    "approve_inbox_detection": _execute_approve_detection,
    "dismiss_inbox_detection": _execute_dismiss_detection,
    "dismiss_payment_reminder": _execute_dismiss_reminder,
}


def get_owned_action(
    db: Session,
    user_id: str,
    action_id: UUID,
    *,
    for_update: bool = False,
) -> AgentAction:
    if isinstance(action_id, str):
        try:
            action_id = UUID(action_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Assistant action not found")
    query = db.query(AgentAction).filter(
        AgentAction.id == action_id,
        AgentAction.user_id == user_id,
    )
    if for_update:
        query = query.with_for_update()
    action = query.first()
    if not action:
        raise HTTPException(status_code=404, detail="Assistant action not found")
    return action


def confirm_action(db: Session, user_id: str, action_id: UUID) -> dict:
    action = get_owned_action(db, user_id, action_id, for_update=True)
    if action.status == "completed":
        return serialize_action(action)
    if action.status != "pending":
        raise HTTPException(status_code=409, detail=f"This action is already {action.status}")
    if action.expires_at < utcnow():
        action.status = "expired"
        action.resolved_at = utcnow()
        db.commit()
        raise HTTPException(status_code=409, detail="This action expired. Ask the assistant again.")

    executor = EXECUTORS.get(action.action_type)
    if not executor:
        raise HTTPException(status_code=400, detail="Unsupported assistant action")
    try:
        _assert_fresh(action, db, user_id)
        result = executor(action, db, user_id)
        action.status = "completed"
        action.result_json = result
        action.error_code = None
        action.error_message = None
        action.resolved_at = utcnow()
        action.updated_at = utcnow()
        db.commit()
        db.refresh(action)
        return serialize_action(action)
    except HTTPException as exc:
        db.rollback()
        failed = get_owned_action(db, user_id, action_id)
        failed.status = "failed"
        failed.error_code = "stale_or_invalid"
        failed.error_message = str(exc.detail)[:300]
        failed.resolved_at = utcnow()
        failed.updated_at = utcnow()
        db.commit()
        raise
    except Exception:
        db.rollback()
        failed = get_owned_action(db, user_id, action_id)
        failed.status = "failed"
        failed.error_code = "execution_failed"
        failed.error_message = "The action could not be completed. No change was applied."
        failed.resolved_at = utcnow()
        failed.updated_at = utcnow()
        db.commit()
        raise


def reject_action(db: Session, user_id: str, action_id: UUID) -> dict:
    action = get_owned_action(db, user_id, action_id, for_update=True)
    if action.status == "rejected":
        return serialize_action(action)
    if action.status != "pending":
        raise HTTPException(status_code=409, detail=f"This action is already {action.status}")
    action.status = "rejected"
    action.resolved_at = utcnow()
    action.updated_at = utcnow()
    db.commit()
    db.refresh(action)
    return serialize_action(action)
