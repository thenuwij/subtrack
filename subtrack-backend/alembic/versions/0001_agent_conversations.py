"""Persist agent conversations.

The production database predates Alembic. This first revision deliberately
owns only the new agent tables; legacy tables remain represented by the
SQLAlchemy models and will be brought under migrations as they change.

The app previously used ``Base.metadata.create_all``. A development reload can
therefore have created an early draft of these tables before Alembic runs. The
online migration adopts that draft, preserves any rows, and adds the finalized
ordering columns instead of failing with "table already exists".

Revision ID: 0001_agent_conversations
Revises: None
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_agent_conversations"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_threads() -> None:
    op.create_table(
        "agent_threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("next_message_sequence", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_threads_archived", "agent_threads", ["archived"])
    op.create_index("ix_agent_threads_user_id", "agent_threads", ["user_id"])
    op.create_index(
        "ix_agent_threads_user_updated", "agent_threads", ["user_id", "updated_at"]
    )


def _create_messages() -> None:
    op.create_table(
        "agent_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reply_to_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_message_id", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["reply_to_id"], ["agent_messages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["agent_threads.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "thread_id",
            "client_message_id",
            name="uq_agent_messages_thread_client_id",
        ),
        sa.UniqueConstraint(
            "thread_id", "sequence", name="uq_agent_messages_thread_sequence"
        ),
    )
    op.create_index(
        "ix_agent_messages_thread_sequence",
        "agent_messages",
        ["thread_id", "sequence"],
    )
    op.create_index("ix_agent_messages_user_id", "agent_messages", ["user_id"])
    op.create_index(
        "ix_agent_messages_user_thread", "agent_messages", ["user_id", "thread_id"]
    )


def upgrade() -> None:
    # Static SQL has no database to inspect. Emit the clean-install path.
    if context.is_offline_mode():
        _create_threads()
        _create_messages()
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "agent_threads" not in tables:
        _create_threads()
    else:
        thread_columns = {column["name"] for column in inspector.get_columns("agent_threads")}
        if "next_message_sequence" not in thread_columns:
            op.add_column(
                "agent_threads",
                sa.Column(
                    "next_message_sequence",
                    sa.Integer(),
                    server_default=sa.text("0"),
                    nullable=False,
                ),
            )
            op.alter_column(
                "agent_threads", "next_message_sequence", server_default=None
            )

    # Refresh after DDL so subsequent existence checks see the current schema.
    inspector = sa.inspect(bind)
    if "agent_messages" not in set(inspector.get_table_names()):
        _create_messages()
        return

    message_columns = {column["name"] for column in inspector.get_columns("agent_messages")}
    if "sequence" not in message_columns:
        op.add_column(
            "agent_messages",
            sa.Column("sequence", sa.Integer(), nullable=True),
        )
        # Preserve draft conversations deterministically. UUID breaks ties for
        # messages written in the same transaction and therefore sharing a
        # timestamp.
        op.execute(sa.text("""
            WITH numbered AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY thread_id
                           ORDER BY created_at, id
                       )::integer AS sequence
                FROM agent_messages
            )
            UPDATE agent_messages AS message
            SET sequence = numbered.sequence
            FROM numbered
            WHERE message.id = numbered.id
        """))
        op.alter_column("agent_messages", "sequence", nullable=False)

    inspector = sa.inspect(bind)
    constraint_names = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("agent_messages")
    }
    if "uq_agent_messages_thread_sequence" not in constraint_names:
        op.create_unique_constraint(
            "uq_agent_messages_thread_sequence",
            "agent_messages",
            ["thread_id", "sequence"],
        )

    index_names = {
        index["name"] for index in inspector.get_indexes("agent_messages")
    }
    if "ix_agent_messages_thread_sequence" not in index_names:
        op.create_index(
            "ix_agent_messages_thread_sequence",
            "agent_messages",
            ["thread_id", "sequence"],
        )

    op.execute(sa.text("""
        UPDATE agent_threads AS thread
        SET next_message_sequence = COALESCE((
            SELECT MAX(message.sequence)
            FROM agent_messages AS message
            WHERE message.thread_id = thread.id
        ), 0)
    """))


def downgrade() -> None:
    op.drop_table("agent_messages")
    op.drop_table("agent_threads")
