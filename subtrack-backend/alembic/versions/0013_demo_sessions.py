"""Track short-lived demo sandboxes.

Revision ID: 0013_demo_sessions
Revises: 0012_onboarding_state
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "0013_demo_sessions"
down_revision: str | Sequence[str] | None = "0012_onboarding_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_table() -> None:
    op.create_table(
        "demo_sessions",
        sa.Column("demo_user_id", sa.String(length=64), nullable=False),
        sa.Column("client_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("demo_user_id"),
    )
    op.create_index("ix_demo_sessions_client_hash", "demo_sessions", ["client_hash"])
    op.create_index("ix_demo_sessions_created_at", "demo_sessions", ["created_at"])
    op.create_index("ix_demo_sessions_expires_at", "demo_sessions", ["expires_at"])


def upgrade() -> None:
    if context.is_offline_mode():
        _create_table()
        return
    if "demo_sessions" not in sa.inspect(op.get_bind()).get_table_names():
        _create_table()


def downgrade() -> None:
    op.drop_table("demo_sessions")
