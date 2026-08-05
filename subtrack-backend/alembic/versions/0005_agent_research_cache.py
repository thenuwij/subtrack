"""Cache cited alternative research.

Revision ID: 0005_agent_research_cache
Revises: 0004_agent_actions_and_trials
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005_agent_research_cache"
down_revision: Union[str, Sequence[str], None] = "0004_agent_actions_and_trials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_cache() -> None:
    op.create_table(
        "agent_research_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("market", sa.String(length=80), nullable=False),
        sa.Column("requirements", sa.String(length=500), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "fingerprint",
            name="uq_agent_research_cache_user_fingerprint",
        ),
    )
    op.create_index(
        "ix_agent_research_cache_user_id", "agent_research_cache", ["user_id"]
    )
    op.create_index(
        "ix_agent_research_cache_subscription_id",
        "agent_research_cache",
        ["subscription_id"],
    )
    op.create_index(
        "ix_agent_research_cache_user_created",
        "agent_research_cache",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_agent_research_cache_expires", "agent_research_cache", ["expires_at"]
    )


def upgrade() -> None:
    if context.is_offline_mode():
        _create_cache()
        return
    if "agent_research_cache" not in set(sa.inspect(op.get_bind()).get_table_names()):
        _create_cache()


def downgrade() -> None:
    op.drop_table("agent_research_cache")
