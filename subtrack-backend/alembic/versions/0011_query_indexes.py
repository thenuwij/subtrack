"""Add indexes for production read paths and foreign-key maintenance.

Revision ID: 0011_query_indexes
Revises: 0010_duplicate_dismissals

Subtrack's deploy hook creates missing tables from current metadata before it
runs Alembic, while legacy databases can contain only a subset of today's
columns. This migration therefore adopts indexes that already exist and skips
an index when its legacy table does not yet contain every required column.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "0011_query_indexes"
down_revision: str | Sequence[str] | None = "0010_duplicate_dismissals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "ix_subscriptions_user_active_name",
        "subscriptions",
        ("user_id", "is_active", "name"),
    ),
    (
        "ix_subscription_changes_user_changed",
        "subscription_changes",
        ("user_id", "changed_at"),
    ),
    (
        "ix_gmail_accounts_scan_started",
        "gmail_accounts",
        ("scan_status", "scan_started_at"),
    ),
    (
        "ix_detected_subscriptions_user_status_charge",
        "detected_subscriptions",
        ("user_id", "status", "charge_count", "detected_at"),
    ),
    (
        "ix_payment_reminders_user_active_created",
        "payment_reminders",
        ("user_id", "is_active", "created_at"),
    ),
    (
        "ix_agent_threads_user_archived_updated",
        "agent_threads",
        ("user_id", "archived", "updated_at"),
    ),
    (
        "ix_agent_messages_user_role_created",
        "agent_messages",
        ("user_id", "role", "created_at"),
    ),
    (
        "ix_agent_messages_status_updated",
        "agent_messages",
        ("status", "updated_at"),
    ),
    (
        "ix_agent_messages_reply_sequence",
        "agent_messages",
        ("reply_to_id", "sequence"),
    ),
    (
        "ix_duplicate_dismissals_subscription_a",
        "duplicate_dismissals",
        ("subscription_a_id",),
    ),
    (
        "ix_duplicate_dismissals_subscription_b",
        "duplicate_dismissals",
        ("subscription_b_id",),
    ),
)


def upgrade() -> None:
    if context.is_offline_mode():
        for name, table, columns in INDEXES:
            op.create_index(name, table, list(columns))
        return

    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for name, table, columns in INDEXES:
        if table not in tables:
            continue
        available_columns = {column["name"] for column in inspector.get_columns(table)}
        existing_indexes = {index["name"] for index in inspector.get_indexes(table)}
        if set(columns).issubset(available_columns) and name not in existing_indexes:
            op.create_index(name, table, list(columns))


def downgrade() -> None:
    if context.is_offline_mode():
        for name, table, _columns in reversed(INDEXES):
            op.drop_index(name, table_name=table)
        return

    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for name, table, _columns in reversed(INDEXES):
        if table not in tables:
            continue
        existing_indexes = {index["name"] for index in inspector.get_indexes(table)}
        if name in existing_indexes:
            op.drop_index(name, table_name=table)
