from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "0014_drop_legacy_tables"
down_revision: str | Sequence[str] | None = "0013_demo_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_TABLES = ("savings_goals", "income", "budgets", "expenses")


def upgrade() -> None:
    if context.is_offline_mode():
        for table in LEGACY_TABLES:
            op.execute(f"DROP TABLE IF EXISTS {table}")
        return
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in LEGACY_TABLES:
        if table in existing:
            op.drop_table(table)


def downgrade() -> None:
    pass
