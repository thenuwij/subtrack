"""Add in-app payment and trial reminders.

Revision ID: 0003_payment_reminders
Revises: 0002_agent_page_context
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003_payment_reminders"
down_revision: Union[str, Sequence[str], None] = "0002_agent_page_context"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_table() -> None:
    op.create_table(
        "payment_reminders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("days_before", sa.Integer(), nullable=False),
        sa.Column("target_date", sa.DateTime(), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("dismissed_for", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_reminders_user_id", "payment_reminders", ["user_id"])
    op.create_index("ix_payment_reminders_subscription_id", "payment_reminders", ["subscription_id"])
    op.create_index(
        "ix_payment_reminders_user_active", "payment_reminders", ["user_id", "is_active"]
    )
    op.create_index(
        "ix_payment_reminders_user_subscription",
        "payment_reminders",
        ["user_id", "subscription_id"],
    )


def upgrade() -> None:
    if not context.is_offline_mode():
        tables = set(sa.inspect(op.get_bind()).get_table_names())
        if "payment_reminders" in tables:
            return
    _create_table()


def downgrade() -> None:
    op.drop_table("payment_reminders")
