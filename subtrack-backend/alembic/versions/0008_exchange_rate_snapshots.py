"""Persist a bounded shared exchange-rate snapshot cache.

Revision ID: 0008_exchange_rate_snapshots
Revises: 0007_flexible_recurring_payments

The deploy command registers SQLAlchemy metadata before applying Alembic, so
the online path deliberately adopts the table when ``create_all`` made it.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "0008_exchange_rate_snapshots"
down_revision: str | Sequence[str] | None = "0007_flexible_recurring_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_table() -> None:
    op.create_table(
        "exchange_rate_snapshots",
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("rates", sa.JSON(), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=32),
            server_default="frankfurter",
            nullable=False,
        ),
        sa.Column("provider_date", sa.String(length=10), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "base_currency IN ('AUD', 'USD', 'GBP', 'SGD', 'EUR', 'JPY')",
            name="ck_exchange_rate_snapshots_supported_base",
        ),
        sa.PrimaryKeyConstraint("base_currency"),
    )


def upgrade() -> None:
    if context.is_offline_mode():
        _create_table()
        return
    if "exchange_rate_snapshots" not in sa.inspect(op.get_bind()).get_table_names():
        _create_table()


def downgrade() -> None:
    op.drop_table("exchange_rate_snapshots")
