"""Authenticated export and deletion of a user's Subtrack application data."""

from __future__ import annotations

import enum
import json
import logging
import math
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.middleware.auth import verify_token
from app.models import (
    AgentAction,
    AgentMessage,
    AgentResearchCache,
    AgentThread,
    DetectedSubscription,
    DuplicateDismissal,
    GmailAccount,
    GmailOAuthState,
    PaymentReminder,
    Subscription,
    SubscriptionChange,
    UserPreference,
)
from app.services.gmail_access import revoke_encrypted_refresh_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/account", tags=["account"])

EXPORT_SCHEMA_VERSION = 1
EXPORT_BATCH_SIZE = 250


@dataclass(frozen=True)
class ExportResource:
    name: str
    model: type
    fields: tuple[str, ...]
    order_by: tuple[str, ...]


# This is deliberately an allow-list. A future secret-bearing column must not
# appear in an export merely because it was added to an ORM model. In
# particular, Gmail refresh tokens and one-time OAuth/PKCE state are omitted.
EXPORT_RESOURCES: tuple[ExportResource, ...] = (
    ExportResource(
        "subscriptions",
        Subscription,
        (
            "id", "name", "category", "amount", "full_amount", "share_ratio",
            "split_mode", "source_domain", "source_key", "currency",
            "exchange_rate", "converted_amount", "cycle", "interval_unit",
            "interval_count", "next_due", "recurrence_end_at", "trial_ends_at",
            "status", "paused_until", "cancellation_effective_at", "amount_type",
            "spending_type", "is_active", "created_at",
        ),
        ("created_at", "id"),
    ),
    ExportResource(
        "duplicate_dismissals",
        DuplicateDismissal,
        (
            "id", "subscription_a_id", "subscription_b_id", "created_at",
        ),
        ("created_at", "id"),
    ),
    ExportResource(
        "subscription_changes",
        SubscriptionChange,
        (
            "id", "subscription_id", "name", "kind", "old_monthly",
            "new_monthly", "currency", "changed_at",
        ),
        ("changed_at", "id"),
    ),
    ExportResource(
        "gmail_connection",
        GmailAccount,
        (
            "email_address", "connected_at", "last_scanned_at", "scan_status",
            "scan_error", "scan_started_at", "scan_heartbeat_at", "scan_stage",
            "scan_processed", "scan_total", "scan_partial", "scan_message",
        ),
        ("user_id",),
    ),
    ExportResource(
        "gmail_detections",
        DetectedSubscription,
        (
            "id", "merchant", "sender_domain", "product_key", "category", "cycle",
            "interval_unit", "interval_count", "cadence_confidence",
            "cadence_evidence", "next_due", "due_date_confidence",
            "due_date_evidence", "amount_type", "amount", "currency",
            "previous_amount", "cancelled", "confidence", "charge_count",
            "trial_ends_at", "existing_subscription_id", "similar_subscription_id",
            "similar_reason", "status", "detected_at", "resolved_at",
        ),
        ("detected_at", "id"),
    ),
    ExportResource(
        "preferences",
        UserPreference,
        ("base_currency", "monthly_income", "timezone", "updated_at"),
        ("user_id",),
    ),
    ExportResource(
        "reminders",
        PaymentReminder,
        (
            "id", "subscription_id", "kind", "days_before", "target_date", "note",
            "is_active", "dismissed_for", "created_at", "updated_at",
        ),
        ("created_at", "id"),
    ),
    ExportResource(
        "assistant_threads",
        AgentThread,
        (
            "id", "title", "archived", "next_message_sequence", "created_at",
            "updated_at",
        ),
        ("created_at", "id"),
    ),
    ExportResource(
        "assistant_messages",
        AgentMessage,
        (
            "id", "thread_id", "role", "sequence", "content", "status",
            "reply_to_id", "client_message_id", "error_code", "context_json",
            "created_at", "updated_at",
        ),
        ("created_at", "id"),
    ),
    ExportResource(
        "assistant_actions",
        AgentAction,
        (
            "id", "thread_id", "assistant_message_id", "action_type", "payload_json",
            "expected_json", "summary", "description", "fingerprint", "status",
            "result_json", "error_code", "error_message", "expires_at",
            "resolved_at", "created_at", "updated_at",
        ),
        ("created_at", "id"),
    ),
    ExportResource(
        "assistant_research_cache",
        AgentResearchCache,
        (
            "id", "subscription_id", "fingerprint", "market", "requirements",
            "result_json", "expires_at", "created_at",
        ),
        ("created_at", "id"),
    ),
)


# Child rows precede their parents. Core DELETE statements avoid loading a
# user's entire history into application memory and keep the operation inside
# one database transaction.
DELETE_ORDER: tuple[tuple[str, type], ...] = (
    ("gmail_oauth_states", GmailOAuthState),
    ("assistant_actions", AgentAction),
    ("assistant_messages", AgentMessage),
    ("assistant_threads", AgentThread),
    ("assistant_research_cache", AgentResearchCache),
    ("reminders", PaymentReminder),
    ("gmail_detections", DetectedSubscription),
    ("duplicate_dismissals", DuplicateDismissal),
    ("subscription_changes", SubscriptionChange),
    ("subscriptions", Subscription),
    ("gmail_connection", GmailAccount),
    ("preferences", UserPreference),
)


class DeleteAppDataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["DELETE MY SUBTRACK DATA"]


def _json_compatible(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        # Legacy databases could contain values from before finite-number
        # validation. Preserve their meaning without emitting invalid JSON.
        return value if math.isfinite(value) else str(value)
    if isinstance(value, enum.Enum):
        return _json_compatible(value.value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_compatible(item) for item in value]
    return str(value)


def _encoded(value: Any) -> bytes:
    return json.dumps(
        _json_compatible(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _record(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: _json_compatible(getattr(row, field)) for field in fields}


def _stream_user_export(user_id: str) -> Generator[bytes, None, None]:
    """Stream a complete, consistently ordered export with bounded memory."""

    db = SessionLocal()
    try:
        exported_at = datetime.now(timezone.utc)
        yield b'{"schema_version":'
        yield _encoded(EXPORT_SCHEMA_VERSION)
        yield b',"exported_at":'
        yield _encoded(exported_at)
        yield b',"scope":"subtrack_application_data","identity":{"user_id":'
        yield _encoded(user_id)
        yield b'},"excluded":["gmail_refresh_token","temporary_oauth_credentials","shared_exchange_rates","supabase_auth_identity"],"data":{'

        for resource_index, resource in enumerate(EXPORT_RESOURCES):
            if resource_index:
                yield b","
            yield _encoded(resource.name)
            yield b":["

            model = resource.model
            statement = (
                select(model)
                .where(model.user_id == user_id)
                .order_by(*(getattr(model, name) for name in resource.order_by))
                .execution_options(stream_results=True, yield_per=EXPORT_BATCH_SIZE)
            )
            first = True
            for row in db.scalars(statement):
                if not first:
                    yield b","
                yield _encoded(_record(row, resource.fields))
                first = False

            yield b"]"

        yield b"}}"
    finally:
        db.close()


@router.get("/export")
def export_app_data(user_id: str = Depends(verify_token)) -> StreamingResponse:
    """Download all exportable Subtrack app data owned by the caller."""

    filename = f"subtrack-data-{datetime.now(timezone.utc).date().isoformat()}.json"
    return StreamingResponse(
        _stream_user_export(user_id),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Export-Schema-Version": str(EXPORT_SCHEMA_VERSION),
        },
    )


def _delete_owned_rows(db: Session, user_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for resource_name, model in DELETE_ORDER:
        result = db.execute(delete(model).where(model.user_id == user_id))
        counts[resource_name] = max(0, result.rowcount or 0)
    return counts


@router.delete("/data")
def delete_app_data(
    body: DeleteAppDataRequest,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),  # noqa: B008 - FastAPI dependency injection
) -> dict[str, Any]:
    """Delete every current app-owned record for the authenticated user.

    Supabase owns the sign-in identity and this backend has no service-role
    credential, so the response says so explicitly rather than claiming the
    external identity was removed.
    """

    del body  # Pydantic has already enforced the destructive confirmation.

    encrypted_token = db.execute(
        select(GmailAccount.refresh_token_encrypted).where(
            GmailAccount.user_id == user_id
        )
    ).scalar_one_or_none()
    # End the read transaction before the complete local deletion transaction.
    # Google revocation is attempted only after local deletion succeeds, so a
    # database rollback never leaves an otherwise-connected row holding a
    # refresh token that was already invalidated externally.
    db.rollback()

    try:
        counts = _delete_owned_rows(db, user_id)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(
            "Transactional app-data deletion failed (%s)",
            type(exc).__name__,
            extra={"user_id": user_id},
        )
        raise HTTPException(
            status_code=500,
            detail="Your data was not deleted because the operation could not complete safely.",
        ) from exc

    revocation = revoke_encrypted_refresh_token(encrypted_token)

    logger.info("User app data deleted", extra={"user_id": user_id})
    return {
        "deleted": True,
        "scope": "subtrack_application_data",
        "deleted_records": counts,
        "gmail_revocation": revocation.value,
        "supabase_auth_identity_deleted": False,
        "message": (
            "Your Subtrack application data was deleted. Your Supabase sign-in "
            "identity remains because this API is not configured with Supabase "
            "administrator credentials."
        ),
    }
