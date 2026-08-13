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
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AgentAction,
    AgentMessage,
    AgentResearchCache,
    AmountType,
    BillingCycle,
    Category,
    ChangeKind,
    DetectedSubscription,
    DetectionStatus,
    PaymentReminder,
    PaymentStatus,
    RecurrenceUnit,
    SpendingType,
    Subscription,
    SubscriptionChange,
    UserPreference,
)
from app.routers.detected import ApproveOverrides, apply_approval
from app.routers.rates import conversion_for_storage
from app.routers.subscriptions import (
    log_change,
    retarget_detection_links,
)
from app.services.duplicates import (
    canonical_duplicate_pair,
    delete_duplicate_dismissals_for_subscription,
    persist_duplicate_dismissal,
)
from app.services.recurrence import (
    Cadence,
    cadence_for,
    cadence_label,
    effective_status,
    legacy_cycle_for,
    monthly_equivalent,
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
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False,
    )


class AddPayment(StrictAction):
    name: str = Field(min_length=1, max_length=160)
    category: Category
    amount: float = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    # ``cycle`` accepts pending proposals created before flexible cadence.
    cycle: BillingCycle | None = None
    interval_unit: RecurrenceUnit | None = None
    interval_count: int | None = Field(default=None, ge=1, le=1200)
    next_due: datetime | None = None
    trial_ends_at: datetime | None = None
    recurrence_end_at: datetime | None = None
    status: PaymentStatus = PaymentStatus.active
    paused_until: datetime | None = None
    cancellation_effective_at: datetime | None = None
    amount_type: AmountType = AmountType.fixed
    spending_type: SpendingType = SpendingType.unspecified

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str) -> str:
        value = value.upper()
        if not value.isalpha():
            raise ValueError("Currency must be a three-letter ISO code")
        return value

    @model_validator(mode="after")
    def valid_cadence(self):
        if (self.interval_unit is None) != (self.interval_count is None):
            raise ValueError("Billing interval unit and count must be provided together")
        if self.interval_unit is None and self.cycle is None:
            raise ValueError("A billing interval is required")
        if self.status == PaymentStatus.cancelling and self.cancellation_effective_at is None:
            raise ValueError("A cancelling payment needs its cancellation effective date")
        if (
            self.status == PaymentStatus.paused
            and self.paused_until is not None
            and utc_naive(self.paused_until).date() <= utcnow().date()
        ):
            raise ValueError("The pause-until date must be in the future")
        return self


class UpdatePayment(StrictAction):
    subscription_id: UUID
    name: str | None = Field(default=None, min_length=1, max_length=160)
    category: Category | None = None
    amount: float | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    cycle: BillingCycle | None = None
    interval_unit: RecurrenceUnit | None = None
    interval_count: int | None = Field(default=None, ge=1, le=1200)
    next_due: datetime | None = None
    recurrence_end_at: datetime | None = None
    status: PaymentStatus | None = None
    paused_until: datetime | None = None
    cancellation_effective_at: datetime | None = None
    amount_type: AmountType | None = None
    spending_type: SpendingType | None = None
    # Null means "leave unchanged" in assistant tool payloads. Explicitly
    # clearing a saved lifecycle date therefore uses this allow-listed field,
    # which avoids every unrelated AI edit wiping dates accidentally.
    clear_fields: list[Literal[
        "next_due", "recurrence_end_at", "paused_until",
        "cancellation_effective_at",
    ]] = Field(default_factory=list, max_length=4)

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.upper()
        if not value.isalpha():
            raise ValueError("Currency must be a three-letter ISO code")
        return value

    @model_validator(mode="after")
    def has_change(self):
        values = self.model_dump(exclude={"subscription_id", "clear_fields"})
        if not any(value is not None for value in values.values()) and not self.clear_fields:
            raise ValueError("At least one field must be changed")
        if (self.interval_unit is None) != (self.interval_count is None):
            raise ValueError("Billing interval unit and count must be updated together")
        return self


def _action_cadence(item: AddPayment | UpdatePayment) -> Cadence:
    if item.interval_unit is not None and item.interval_count is not None:
        return Cadence(_enum(item.interval_unit), item.interval_count)
    return cadence_for(item.cycle)


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


class DismissDuplicateSuggestion(StrictAction):
    subscription_id: UUID
    possible_duplicate_id: UUID

    @model_validator(mode="after")
    def canonical_distinct_pair(self):
        first, second = canonical_duplicate_pair(
            self.subscription_id,
            self.possible_duplicate_id,
        )
        self.subscription_id = first
        self.possible_duplicate_id = second
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
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: Category | None = None
    amount: float | None = Field(default=None, gt=0)
    interval_unit: RecurrenceUnit | None = None
    interval_count: int | None = Field(default=None, ge=1, le=1200)
    next_due: datetime | None = None
    trial_ends_at: datetime | None = None
    amount_type: AmountType | None = None
    duplicate_resolution: Literal["keep_both", "replace_existing"] | None = None
    # Tool payload nulls mean "use the detection" for backward compatibility.
    # Clearing inferred dates must therefore be an explicit, confirmation-gated
    # instruction. Keep this allow-list deliberately narrower than the general
    # payment update action: these are the only nullable detection fields that
    # approval is allowed to erase.
    clear_fields: list[Literal["next_due", "trial_ends_at"]] = Field(
        default_factory=list,
        max_length=2,
    )

    @model_validator(mode="after")
    def valid_cadence_pair(self):
        if (self.interval_unit is None) != (self.interval_count is None):
            raise ValueError("Billing interval unit and count must be provided together")
        if len(set(self.clear_fields)) != len(self.clear_fields):
            raise ValueError("Each field can only be cleared once")
        conflicts = [
            field_name
            for field_name in self.clear_fields
            if getattr(self, field_name) is not None
        ]
        if conflicts:
            raise ValueError(
                f"Cannot both set and clear {', '.join(conflicts)}"
            )
        return self


class DismissDetection(StrictAction):
    detection_id: UUID


class DismissReminder(StrictAction):
    reminder_id: UUID


ACTION_MODELS: dict[str, type[StrictAction]] = {
    "propose_add_recurring_payment": AddPayment,
    "propose_update_recurring_payment": UpdatePayment,
    "propose_remove_recurring_payment": RemovePayment,
    "propose_merge_recurring_payments": MergePayments,
    "propose_dismiss_duplicate_suggestion": DismissDuplicateSuggestion,
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
                "interval_unit": {
                    "type": "string", "enum": [item.value for item in RecurrenceUnit],
                },
                "interval_count": {"type": "integer", "minimum": 1, "maximum": 1200},
                "next_due": {"type": ["string", "null"], "format": "date-time"},
                "trial_ends_at": {"type": ["string", "null"], "format": "date-time"},
                "recurrence_end_at": {"type": ["string", "null"], "format": "date-time"},
                "status": {"type": "string", "enum": [item.value for item in PaymentStatus]},
                "paused_until": {"type": ["string", "null"], "format": "date-time"},
                "cancellation_effective_at": {
                    "type": ["string", "null"], "format": "date-time",
                },
                "amount_type": {"type": "string", "enum": [item.value for item in AmountType]},
                "spending_type": {
                    "type": "string", "enum": [item.value for item in SpendingType],
                },
            },
            "required": [
                "name", "category", "amount", "currency", "interval_unit",
                "interval_count", "next_due", "trial_ends_at", "recurrence_end_at",
                "status", "paused_until", "cancellation_effective_at", "amount_type",
                "spending_type",
            ],
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
                "interval_unit": {
                    "type": ["string", "null"],
                    "enum": [item.value for item in RecurrenceUnit] + [None],
                },
                "interval_count": {
                    "type": ["integer", "null"], "minimum": 1, "maximum": 1200,
                },
                "next_due": {"type": ["string", "null"], "format": "date-time"},
                "recurrence_end_at": {"type": ["string", "null"], "format": "date-time"},
                "status": {
                    "type": ["string", "null"],
                    "enum": [item.value for item in PaymentStatus] + [None],
                },
                "paused_until": {"type": ["string", "null"], "format": "date-time"},
                "cancellation_effective_at": {
                    "type": ["string", "null"], "format": "date-time",
                },
                "amount_type": {
                    "type": ["string", "null"],
                    "enum": [item.value for item in AmountType] + [None],
                },
                "spending_type": {
                    "type": ["string", "null"],
                    "enum": [item.value for item in SpendingType] + [None],
                },
                "clear_fields": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "next_due", "recurrence_end_at", "paused_until",
                            "cancellation_effective_at",
                        ],
                    },
                    "maxItems": 4,
                    "uniqueItems": True,
                },
            },
            "required": [
                "subscription_id", "name", "category", "amount", "currency",
                "interval_unit", "interval_count", "next_due", "recurrence_end_at",
                "status", "paused_until", "cancellation_effective_at", "amount_type",
                "spending_type", "clear_fields",
            ],
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
        "name": "propose_dismiss_duplicate_suggestion",
        "description": (
            "Prepare marking two owned tracked payments as intentionally different. "
            "Confirmation hides this pair from future duplicate suggestions without "
            "changing or deleting either payment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subscription_id": {"type": "string", "format": "uuid"},
                "possible_duplicate_id": {"type": "string", "format": "uuid"},
            },
            "required": ["subscription_id", "possible_duplicate_id"],
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
                "name": {"type": ["string", "null"], "minLength": 1, "maxLength": 200},
                "category": {
                    "type": ["string", "null"],
                    "enum": [item.value for item in Category] + [None],
                },
                "amount": {"type": ["number", "null"], "exclusiveMinimum": 0},
                "interval_unit": {
                    "type": ["string", "null"],
                    "enum": [item.value for item in RecurrenceUnit] + [None],
                },
                "interval_count": {
                    "type": ["integer", "null"], "minimum": 1, "maximum": 1200,
                },
                "next_due": {"type": ["string", "null"], "format": "date-time"},
                "trial_ends_at": {
                    "type": ["string", "null"], "format": "date-time",
                },
                "amount_type": {
                    "type": ["string", "null"],
                    "enum": [item.value for item in AmountType] + [None],
                },
                "duplicate_resolution": {
                    "type": ["string", "null"],
                    "enum": ["keep_both", "replace_existing", None],
                },
                "clear_fields": {
                    "type": "array",
                    "description": (
                        "Dates to clear explicitly after confirmation. A null date leaves "
                        "the inbox detection unchanged; use this field only when the user "
                        "asked to remove a stale next-due or trial-end date."
                    ),
                    "items": {
                        "type": "string",
                        "enum": ["next_due", "trial_ends_at"],
                    },
                    "maxItems": 2,
                    "uniqueItems": True,
                },
            },
            "required": [
                "detection_id", "name", "category", "amount", "interval_unit",
                "interval_count", "next_due", "trial_ends_at", "amount_type",
                "duplicate_resolution", "clear_fields",
            ],
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


def _owned_subscription(
    db: Session,
    user_id: str,
    identifier: UUID,
    *,
    for_update: bool = False,
) -> Subscription:
    query = db.query(Subscription).filter(
        Subscription.id == identifier,
        Subscription.user_id == user_id,
        Subscription.is_active == True,  # noqa: E712
    )
    if for_update:
        query = query.with_for_update()
    row = query.first()
    if not row:
        raise HTTPException(status_code=404, detail="Recurring payment not found")
    return row


def _owned_detection(
    db: Session,
    user_id: str,
    identifier: UUID,
    *,
    for_update: bool = False,
) -> DetectedSubscription:
    query = db.query(DetectedSubscription).filter(
        DetectedSubscription.id == identifier,
        DetectedSubscription.user_id == user_id,
        DetectedSubscription.status == DetectionStatus.pending,
    )
    if for_update:
        query = query.with_for_update()
    row = query.first()
    if not row:
        raise HTTPException(status_code=404, detail="Pending inbox detection not found")
    return row


def _owned_reminder(
    db: Session,
    user_id: str,
    identifier: UUID,
    *,
    for_update: bool = False,
) -> PaymentReminder:
    query = db.query(PaymentReminder).filter(
        PaymentReminder.id == identifier,
        PaymentReminder.user_id == user_id,
        PaymentReminder.is_active == True,  # noqa: E712
    )
    if for_update:
        query = query.with_for_update()
    row = query.first()
    if not row:
        raise HTTPException(status_code=404, detail="Active reminder not found")
    return row


def _subscription_snapshot(row: Subscription) -> dict:
    cadence = cadence_for(row)
    return {
        "id": str(row.id),
        "name": row.name,
        "amount": row.amount,
        "currency": row.currency,
        "cycle": _enum(row.cycle),
        "interval_unit": cadence.unit,
        "interval_count": cadence.count,
        "category": _enum(row.category),
        "next_due": _iso(row.next_due),
        "recurrence_end_at": _iso(row.recurrence_end_at),
        "trial_ends_at": _iso(row.trial_ends_at),
        "status": row.status or "active",
        "paused_until": _iso(row.paused_until),
        "cancellation_effective_at": _iso(row.cancellation_effective_at),
        "amount_type": row.amount_type or "fixed",
        "spending_type": row.spending_type or "unspecified",
        "is_active": bool(row.is_active),
    }


def _detection_snapshot(row: DetectedSubscription) -> dict:
    return {
        "id": str(row.id),
        "merchant": row.merchant,
        "amount": row.amount,
        "currency": row.currency,
        "cycle": _enum(row.cycle),
        "interval_unit": row.interval_unit,
        "interval_count": row.interval_count,
        "cadence_confidence": row.cadence_confidence,
        "next_due": _iso(row.next_due),
        "amount_type": row.amount_type or "fixed",
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
        cadence = _action_cadence(item)
        summary = f"Add {item.name}"
        description = (
            f"Track {item.currency.upper()} {item.amount:.2f} "
            f"{cadence_label(cadence.unit, cadence.count).lower()}."
        )
        if item.amount_type == AmountType.variable:
            description += " The saved amount is an estimate for a variable bill."
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
            for key, value in item.model_dump(
                exclude={"subscription_id", "clear_fields"},
            ).items()
            if value is not None
        ]
        changed.extend(f"clear {key.replace('_', ' ')}" for key in item.clear_fields)
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
    elif tool_name == "propose_dismiss_duplicate_suggestion":
        item = data
        assert isinstance(item, DismissDuplicateSuggestion)
        first = _owned_subscription(db, user_id, item.subscription_id)
        second = _owned_subscription(db, user_id, item.possible_duplicate_id)
        expected = {
            "source": _subscription_snapshot(first),
            "target": _subscription_snapshot(second),
        }
        summary = f"Keep {first.name} and {second.name} separate"
        description = (
            "Remember that these are intentionally different and hide this pair "
            "from future duplicate suggestions. Neither payment will be changed."
        )
    elif tool_name == "propose_add_payment_reminder":
        item = data
        assert isinstance(item, AddReminder)
        sub = _owned_subscription(db, user_id, item.subscription_id)
        lifecycle = effective_status(sub)
        if lifecycle in {PaymentStatus.cancelled.value, PaymentStatus.ended.value}:
            raise HTTPException(
                status_code=422,
                detail="Cancelled or ended payments cannot have active reminders",
            )
        if (
            lifecycle == PaymentStatus.paused.value
            and not sub.paused_until
            and item.target_date is None
        ):
            raise HTTPException(
                status_code=422,
                detail="Add a resume date or choose a fixed reminder date for this paused payment",
            )
        display_target = item.target_date or (
            sub.trial_ends_at if item.kind == "trial_end" else sub.next_due
        )
        if not display_target:
            raise HTTPException(status_code=422, detail="This reminder needs a saved date")
        if utc_naive(display_target).date() < utcnow().date():
            raise HTTPException(status_code=422, detail="The reminder date has already passed")
        expected = {"subscription": _subscription_snapshot(sub)}
        summary = f"Remind you about {sub.name}"
        description = (
            f"Show an in-app {item.kind.replace('_', ' ')} reminder "
            f"{item.days_before} days before {_iso(display_target)[:10]}."
        )
        if item.target_date is None and item.kind != "trial_end":
            description += " It will repeat with the saved payment cadence."
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
        clear_fields = set(item.clear_fields)
        effective_trial_end = (
            None
            if "trial_ends_at" in clear_fields
            else item.trial_ends_at or detection.trial_ends_at
        )
        if "next_due" in clear_fields and effective_trial_end is not None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "A trial end is also the next due date. Clear trial_ends_at as well, "
                    "or keep the next due date."
                ),
            )
        amount = item.amount if item.amount is not None else detection.amount
        if amount is None or amount <= 0:
            raise HTTPException(status_code=422, detail="The price after this trial is needed before approval")
        cadence_unit = _enum(item.interval_unit) if item.interval_unit else detection.interval_unit
        cadence_count = item.interval_count or detection.interval_count
        confidence = _enum(detection.cadence_confidence or "unknown")
        if not cadence_unit or not cadence_count or (
            confidence == "unknown" and item.interval_unit is None
        ):
            raise HTTPException(
                status_code=422,
                detail="Confirm how often this inbox finding repeats before approval",
            )
        cadence = Cadence(cadence_unit, cadence_count)
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
        description = (
            f"Add or update this reviewed inbox finding at "
            f"{detection.currency} {amount:.2f} "
            f"{cadence_label(cadence.unit, cadence.count).lower()}."
        )
        if item.amount_type == AmountType.variable or (
            item.amount_type is None and _enum(detection.amount_type) == AmountType.variable.value
        ):
            description += " Its amount will be labelled as an estimate."
        if "next_due" in clear_fields:
            description += " Its saved next due date will be cleared."
        if "trial_ends_at" in clear_fields:
            description += " Its saved trial end and automatic dashboard reminder will be cleared."
        elif effective_trial_end is not None:
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
    def matches(current: dict, stored: dict) -> bool:
        # Pending actions from the previous release contain the legacy subset.
        # Compare every key that was stored, without invalidating them merely
        # because the current snapshot gained additive cadence fields.
        return all(current.get(key) == value for key, value in stored.items())

    expected = action.expected_json or {}
    # Detection approvals lock the review row before any tracked target, which
    # matches the direct Review endpoint and prevents opposite lock ordering
    # from deadlocking under concurrent UI/assistant confirmations.
    if "detection" in expected:
        detection = _owned_detection(
            db, user_id, UUID(expected["detection"]["id"]), for_update=True,
        )
        if not matches(_detection_snapshot(detection), expected["detection"]):
            raise HTTPException(status_code=409, detail="This inbox finding changed after the action was proposed.")
    if "subscription" in expected:
        sub = _owned_subscription(
            db, user_id, UUID(expected["subscription"]["id"]), for_update=True,
        )
        current = _subscription_snapshot(sub)
        if not matches(current, expected["subscription"]):
            raise HTTPException(status_code=409, detail="This payment changed after the action was proposed. Ask the assistant again.")
    if "source" in expected:
        source_id = UUID(expected["source"]["id"])
        target_id = UUID(expected["target"]["id"])
        locked = {
            row.id: row for row in db.query(Subscription).filter(
                Subscription.user_id == user_id,
                Subscription.is_active == True,  # noqa: E712
                Subscription.id.in_([source_id, target_id]),
            ).order_by(Subscription.id).with_for_update().all()
        }
        source, target = locked.get(source_id), locked.get(target_id)
        if source is None or target is None:
            raise HTTPException(status_code=404, detail="Recurring payment not found")
        if not matches(_subscription_snapshot(source), expected["source"]) or not matches(
            _subscription_snapshot(target), expected["target"]
        ):
            raise HTTPException(status_code=409, detail="One of these payments changed after the merge was proposed.")
    if "reminder" in expected:
        reminder = _owned_reminder(
            db, user_id, UUID(expected["reminder"]["id"]), for_update=True,
        )
        if not matches(_reminder_snapshot(reminder), expected["reminder"]):
            raise HTTPException(status_code=409, detail="This reminder changed after the action was proposed.")


def _execute_add_payment(action: AgentAction, db: Session, user_id: str) -> dict:
    data = AddPayment.model_validate(action.payload_json)
    cadence = _action_cadence(data)
    trial_end = utc_naive(data.trial_ends_at) if data.trial_ends_at else None
    next_due = trial_end or (utc_naive(data.next_due) if data.next_due else None)
    preference = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    base = preference.base_currency if preference else "AUD"
    currency = data.currency.upper()
    converted, exchange_rate, _quality = conversion_for_storage(
        data.amount, currency, base, db,
    )
    sub = Subscription(
        id=uuid4(), user_id=user_id, name=data.name.strip(), category=data.category,
        amount=data.amount, full_amount=None, share_ratio=1.0, split_mode="full",
        currency=currency, exchange_rate=exchange_rate,
        converted_amount=converted,
        cycle=legacy_cycle_for(cadence.unit, cadence.count),
        interval_unit=cadence.unit, interval_count=cadence.count,
        next_due=next_due,
        recurrence_end_at=(
            utc_naive(data.recurrence_end_at) if data.recurrence_end_at else None
        ),
        trial_ends_at=trial_end,
        status=_enum(data.status),
        paused_until=utc_naive(data.paused_until) if data.paused_until else None,
        cancellation_effective_at=(
            utc_naive(data.cancellation_effective_at)
            if data.cancellation_effective_at else None
        ),
        amount_type=_enum(data.amount_type), spending_type=_enum(data.spending_type),
        is_active=data.status not in {PaymentStatus.cancelled, PaymentStatus.ended},
    )
    if sub.recurrence_end_at and sub.next_due and (
        sub.recurrence_end_at.date() < sub.next_due.date()
    ):
        raise HTTPException(
            status_code=422,
            detail="The recurrence end cannot be before the next payment",
        )
    if sub.status == PaymentStatus.cancelling.value and not sub.cancellation_effective_at:
        raise HTTPException(
            status_code=422,
            detail="A cancelling payment needs its cancellation effective date",
        )
    db.add(sub)
    db.flush()
    if trial_end:
        sync_trial_reminder(db, sub)
    log_change(db, sub, ChangeKind.added, None, monthly_equivalent(sub.amount, sub))
    return {
        "subscription_id": str(sub.id), "name": sub.name,
        "cadence": cadence_label(sub),
    }


def _execute_update_payment(action: AgentAction, db: Session, user_id: str) -> dict:
    data = UpdatePayment.model_validate(action.payload_json)
    sub = _owned_subscription(db, user_id, data.subscription_id)
    before = monthly_equivalent(sub.amount, sub)
    before_currency = sub.currency
    fields = data.model_dump(exclude_unset=True)
    fields.pop("subscription_id", None)
    clear_fields = set(fields.pop("clear_fields", []))
    requested_unit = fields.pop("interval_unit", None)
    requested_count = fields.pop("interval_count", None)
    requested_cycle = fields.pop("cycle", None)
    if requested_unit is not None and requested_count is not None:
        cadence = Cadence(_enum(requested_unit), requested_count)
        sub.interval_unit = cadence.unit
        sub.interval_count = cadence.count
        sub.cycle = legacy_cycle_for(cadence.unit, cadence.count)
    elif requested_cycle is not None:
        cadence = cadence_for(requested_cycle)
        sub.interval_unit = cadence.unit
        sub.interval_count = cadence.count
        sub.cycle = legacy_cycle_for(cadence.unit, cadence.count)

    date_fields = {
        "next_due", "recurrence_end_at", "paused_until", "cancellation_effective_at",
    }
    for key in clear_fields:
        setattr(sub, key, None)
    for key, value in fields.items():
        if value is None:
            continue
        if key == "currency":
            value = value.upper()
        elif key in date_fields:
            value = utc_naive(value)
        elif hasattr(value, "value"):
            value = value.value
        setattr(sub, key, value)

    if data.status is not None:
        sub.is_active = data.status not in {
            PaymentStatus.cancelled, PaymentStatus.ended,
        }
    if sub.recurrence_end_at and sub.next_due and (
        sub.recurrence_end_at.date() < sub.next_due.date()
    ):
        raise HTTPException(
            status_code=422,
            detail="The recurrence end cannot be before the next payment",
        )
    if sub.status == PaymentStatus.cancelling.value and not sub.cancellation_effective_at:
        raise HTTPException(
            status_code=422,
            detail="A cancelling payment needs its cancellation effective date",
        )
    if (
        sub.status == PaymentStatus.paused.value
        and sub.paused_until is not None
        and sub.paused_until.date() <= utcnow().date()
    ):
        raise HTTPException(
            status_code=422,
            detail="The pause-until date must be in the future",
        )
    if data.currency is not None or data.amount is not None:
        preference = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
        base = preference.base_currency if preference else "AUD"
        sub.converted_amount, sub.exchange_rate, _quality = conversion_for_storage(
            sub.amount, sub.currency, base, db,
        )
    if not sub.is_active or sub.status in {
        PaymentStatus.cancelled.value, PaymentStatus.ended.value,
    }:
        db.query(PaymentReminder).filter(
            PaymentReminder.user_id == user_id,
            PaymentReminder.subscription_id == sub.id,
        ).update({PaymentReminder.is_active: False}, synchronize_session=False)
    after = monthly_equivalent(sub.amount, sub)
    if sub.currency != before_currency:
        log_change(
            db, sub, ChangeKind.removed, before, None,
            currency=before_currency,
        )
        log_change(db, sub, ChangeKind.added, None, after)
    elif after != before:
        log_change(db, sub, ChangeKind.price_change, before, after)
    return {
        "subscription_id": str(sub.id), "name": sub.name,
        "cadence": cadence_label(sub), "status": _enum(sub.status),
    }


def _execute_remove_payment(action: AgentAction, db: Session, user_id: str) -> dict:
    data = RemovePayment.model_validate(action.payload_json)
    sub = _owned_subscription(db, user_id, data.subscription_id)
    name = sub.name
    log_change(db, sub, ChangeKind.removed, monthly_equivalent(sub.amount, sub), None)
    db.query(PaymentReminder).filter(
        PaymentReminder.user_id == user_id,
        PaymentReminder.subscription_id == sub.id,
    ).delete(synchronize_session=False)
    retarget_detection_links(db, user_id, sub.id, None)
    db.query(AgentResearchCache).filter(
        AgentResearchCache.user_id == user_id,
        AgentResearchCache.subscription_id == sub.id,
    ).delete(synchronize_session=False)
    delete_duplicate_dismissals_for_subscription(db, user_id, sub.id)
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
    db.query(AgentResearchCache).filter(
        AgentResearchCache.user_id == user_id,
        AgentResearchCache.subscription_id == source.id,
    ).delete(synchronize_session=False)
    delete_duplicate_dismissals_for_subscription(db, user_id, source.id)
    db.delete(source)
    return {"removed_subscription_id": str(source.id), "subscription_id": str(target.id), "name": target.name}


def _execute_dismiss_duplicate(
    action: AgentAction,
    db: Session,
    user_id: str,
) -> dict:
    data = DismissDuplicateSuggestion.model_validate(action.payload_json)
    first = _owned_subscription(db, user_id, data.subscription_id)
    second = _owned_subscription(db, user_id, data.possible_duplicate_id)
    row, created = persist_duplicate_dismissal(
        db, user_id, first.id, second.id,
    )
    return {
        "dismissed": True,
        "already_dismissed": not created,
        "subscription_ids": [
            str(row.subscription_a_id), str(row.subscription_b_id),
        ],
    }


def _execute_add_reminder(action: AgentAction, db: Session, user_id: str) -> dict:
    data = AddReminder.model_validate(action.payload_json)
    sub = _owned_subscription(db, user_id, data.subscription_id)
    lifecycle = effective_status(sub)
    if lifecycle in {PaymentStatus.cancelled.value, PaymentStatus.ended.value}:
        raise HTTPException(
            status_code=422,
            detail="Cancelled or ended payments cannot have active reminders",
        )
    if (
        lifecycle == PaymentStatus.paused.value
        and not sub.paused_until
        and data.target_date is None
    ):
        raise HTTPException(
            status_code=422,
            detail="Add a resume date or choose a fixed reminder date for this paused payment",
        )
    explicit_target = utc_naive(data.target_date) if data.target_date else None
    # Trial deadlines are one-off. Renewal/cancellation reminders without an
    # explicit target remain recurrence-based, so they advance next cycle.
    stored_target = (
        (explicit_target or sub.trial_ends_at)
        if data.kind == "trial_end"
        else explicit_target
    )
    validation_target = stored_target or sub.next_due
    if not validation_target or utc_naive(validation_target).date() < utcnow().date():
        raise HTTPException(status_code=422, detail="The reminder needs a future date")
    duplicate = db.query(PaymentReminder).filter(
        PaymentReminder.user_id == user_id,
        PaymentReminder.subscription_id == sub.id,
        PaymentReminder.kind == data.kind,
        PaymentReminder.days_before == data.days_before,
        PaymentReminder.target_date == stored_target,
        PaymentReminder.is_active == True,  # noqa: E712
    ).first()
    if duplicate:
        return {"reminder_id": str(duplicate.id), "subscription_id": str(sub.id), "already_existed": True}
    reminder = PaymentReminder(
        id=uuid4(), user_id=user_id, subscription_id=sub.id, kind=data.kind,
        days_before=data.days_before, target_date=stored_target,
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
        before = monthly_equivalent(sub.amount, sub)
        sub.amount = data.price_after_trial
        preference = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
        base = preference.base_currency if preference else "AUD"
        sub.converted_amount, sub.exchange_rate, _quality = conversion_for_storage(
            sub.amount, sub.currency, base, db,
        )
        after = monthly_equivalent(sub.amount, sub)
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
    overrides: dict = {}
    for key in (
        "name", "category", "amount", "interval_unit", "interval_count",
        "next_due", "trial_ends_at", "amount_type",
    ):
        value = getattr(data, key)
        if value is not None:
            overrides[key] = value
    # Supplying an explicit None preserves Pydantic's fields-set information,
    # which is how the shared Review approval path distinguishes "clear this"
    # from the legacy meaning of an omitted/null override (keep the detection).
    for key in data.clear_fields:
        overrides[key] = None
    if data.duplicate_resolution == "replace_existing":
        overrides["replace_subscription_id"] = detection.similar_subscription_id
    return apply_approval(
        data.detection_id,
        ApproveOverrides(**overrides),
        user_id,
        db,
        commit=False,
    )


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
    "dismiss_duplicate_suggestion": _execute_dismiss_duplicate,
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
            raise HTTPException(status_code=404, detail="Assistant action not found") from None
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
