"""Add one-time encrypted Gmail OAuth handshakes.

Revision ID: 0009_secure_gmail_oauth
Revises: 0008_exchange_rate_snapshots

The old signed-state callback is intentionally not retained as a database
fallback: accepting an unauthenticated callback would preserve the very
account-linking CSRF path this migration closes. Existing Gmail connections
remain valid; only new/reconnect flows use this table.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "0009_secure_gmail_oauth"
down_revision: str | Sequence[str] | None = "0008_exchange_rate_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_table() -> None:
    op.create_table(
        "gmail_oauth_states",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("code_verifier_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "length(state_hash) = 64",
            name="ck_gmail_oauth_states_hash_length",
        ),
        sa.PrimaryKeyConstraint("state_hash"),
    )
    op.create_index(
        "ix_gmail_oauth_states_user_expires",
        "gmail_oauth_states",
        ["user_id", "expires_at"],
    )
    op.create_index(
        "ix_gmail_oauth_states_expires",
        "gmail_oauth_states",
        ["expires_at"],
    )


def upgrade() -> None:
    if context.is_offline_mode():
        _create_table()
        return
    if "gmail_oauth_states" not in sa.inspect(op.get_bind()).get_table_names():
        _create_table()


def downgrade() -> None:
    op.drop_table("gmail_oauth_states")
