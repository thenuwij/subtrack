"""Store structured page context with agent messages.

Revision ID: 0002_agent_page_context
Revises: 0001_agent_conversations
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "0002_agent_page_context"
down_revision: Union[str, Sequence[str], None] = "0001_agent_conversations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not context.is_offline_mode():
        columns = {
            column["name"] for column in sa.inspect(op.get_bind()).get_columns("agent_messages")
        }
        if "context_json" in columns:
            return
    op.add_column("agent_messages", sa.Column("context_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_messages", "context_json")
