"""Add trial metadata and confirmed assistant actions.

Revision ID: 0004_agent_actions_and_trials
Revises: 0003_payment_reminders
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004_agent_actions_and_trials"
down_revision: Union[str, Sequence[str], None] = "0003_payment_reminders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_actions() -> None:
    op.create_table(
        "agent_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assistant_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("action_type", sa.String(length=48), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("expected_json", sa.JSON(), nullable=True),
        sa.Column("summary", sa.String(length=240), nullable=False),
        sa.Column("description", sa.String(length=600), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=300), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["assistant_message_id"], ["agent_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["agent_threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assistant_message_id",
            "fingerprint",
            name="uq_agent_actions_message_fingerprint",
        ),
    )
    op.create_index("ix_agent_actions_user_id", "agent_actions", ["user_id"])
    op.create_index("ix_agent_actions_status", "agent_actions", ["status"])
    op.create_index(
        "ix_agent_actions_user_status", "agent_actions", ["user_id", "status"]
    )
    op.create_index(
        "ix_agent_actions_thread_created", "agent_actions", ["thread_id", "created_at"]
    )


def upgrade() -> None:
    if context.is_offline_mode():
        op.add_column("subscriptions", sa.Column("trial_ends_at", sa.DateTime(), nullable=True))
        op.add_column(
            "detected_subscriptions",
            sa.Column("trial_ends_at", sa.DateTime(), nullable=True),
        )
        _create_actions()
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    subscription_columns = {
        column["name"] for column in inspector.get_columns("subscriptions")
    }
    if "trial_ends_at" not in subscription_columns:
        op.add_column(
            "subscriptions", sa.Column("trial_ends_at", sa.DateTime(), nullable=True)
        )

    detection_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("detected_subscriptions")
    }
    if "trial_ends_at" not in detection_columns:
        op.add_column(
            "detected_subscriptions",
            sa.Column("trial_ends_at", sa.DateTime(), nullable=True),
        )

    if "agent_actions" not in set(sa.inspect(bind).get_table_names()):
        _create_actions()


def downgrade() -> None:
    op.drop_table("agent_actions")
    op.drop_column("detected_subscriptions", "trial_ends_at")
    op.drop_column("subscriptions", "trial_ends_at")
