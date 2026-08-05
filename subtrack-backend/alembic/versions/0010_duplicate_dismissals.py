"""Persist per-user false-positive duplicate decisions.

Revision ID: 0010_duplicate_dismissals
Revises: 0009_secure_gmail_oauth

This is additive and contains no backfill: existing duplicate suggestions are
unchanged until a user explicitly marks a pair as different. Foreign-key
cascades keep the table bounded as tracked records are removed or merged.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "0010_duplicate_dismissals"
down_revision: str | Sequence[str] | None = "0009_secure_gmail_oauth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_table() -> None:
    op.create_table(
        "duplicate_dismissals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("subscription_a_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_b_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "subscription_a_id <> subscription_b_id",
            name="ck_duplicate_dismissals_distinct_pair",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_a_id"], ["subscriptions.id"],
            name="fk_duplicate_dismissals_subscription_a",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_b_id"], ["subscriptions.id"],
            name="fk_duplicate_dismissals_subscription_b",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "subscription_a_id", "subscription_b_id",
            name="uq_duplicate_dismissals_user_pair",
        ),
    )
    op.create_index(
        "ix_duplicate_dismissals_user_created",
        "duplicate_dismissals",
        ["user_id", "created_at"],
    )


def upgrade() -> None:
    # Render's deploy hook currently calls metadata creation before Alembic.
    # Adopt that table if it already exists, while normal Alembic deployments
    # create it here as usual.
    if context.is_offline_mode():
        _create_table()
        return
    if "duplicate_dismissals" not in sa.inspect(op.get_bind()).get_table_names():
        _create_table()


def downgrade() -> None:
    op.drop_table("duplicate_dismissals")
