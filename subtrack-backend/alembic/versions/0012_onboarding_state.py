"""Record when a user finishes or skips the onboarding tour.

Revision ID: 0012_onboarding_state
Revises: 0011_query_indexes
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "0012_onboarding_state"
down_revision: str | Sequence[str] | None = "0011_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_column() -> None:
    op.add_column(
        "user_preferences",
        sa.Column("onboarding_completed_at", sa.DateTime(), nullable=True),
    )
    op.execute(
        "UPDATE user_preferences SET onboarding_completed_at = CURRENT_TIMESTAMP "
        "WHERE onboarding_completed_at IS NULL"
    )


def upgrade() -> None:
    if context.is_offline_mode():
        _add_column()
        return
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("user_preferences")
    }
    if "onboarding_completed_at" not in columns:
        _add_column()


def downgrade() -> None:
    op.drop_column("user_preferences", "onboarding_completed_at")
