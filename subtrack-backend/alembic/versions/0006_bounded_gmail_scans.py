"""Persist bounded Gmail scan progress and worker ownership.

Revision ID: 0006_bounded_gmail_scans
Revises: 0005_agent_research_cache
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "0006_bounded_gmail_scans"
down_revision: Union[str, Sequence[str], None] = "0005_agent_research_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


COLUMNS = (
    sa.Column("scan_heartbeat_at", sa.DateTime(), nullable=True),
    sa.Column("scan_run_id", sa.String(length=36), nullable=True),
    sa.Column("scan_stage", sa.String(length=24), nullable=True),
    sa.Column(
        "scan_processed", sa.Integer(), server_default=sa.text("0"), nullable=False,
    ),
    sa.Column(
        "scan_total", sa.Integer(), server_default=sa.text("0"), nullable=False,
    ),
    sa.Column(
        "scan_partial", sa.Boolean(), server_default=sa.text("false"), nullable=False,
    ),
    sa.Column("scan_message", sa.String(length=300), nullable=True),
)


def upgrade() -> None:
    if context.is_offline_mode():
        for column in COLUMNS:
            op.add_column("gmail_accounts", column)
        op.create_index(
            "ix_gmail_accounts_scan_heartbeat",
            "gmail_accounts",
            ["scan_status", "scan_heartbeat_at"],
        )
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {
        column["name"] for column in inspector.get_columns("gmail_accounts")
    }
    for column in COLUMNS:
        if column.name not in existing:
            op.add_column("gmail_accounts", column)

    index_names = {
        index["name"] for index in sa.inspect(bind).get_indexes("gmail_accounts")
    }
    if "ix_gmail_accounts_scan_heartbeat" not in index_names:
        op.create_index(
            "ix_gmail_accounts_scan_heartbeat",
            "gmail_accounts",
            ["scan_status", "scan_heartbeat_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_gmail_accounts_scan_heartbeat", table_name="gmail_accounts")
    for column in reversed(COLUMNS):
        op.drop_column("gmail_accounts", column.name)
