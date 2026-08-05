"""Add flexible cadence and recurring-payment lifecycle metadata.

Revision ID: 0007_flexible_recurring_payments
Revises: 0006_bounded_gmail_scans

The legacy ``cycle`` enum deliberately remains. New releases write both the
legacy compatibility value and interval unit/count, while previous releases
can continue inserting null interval pairs during a rolling deploy. New code
falls back to ``cycle`` for those rows.
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "0007_flexible_recurring_payments"
down_revision: Union[str, Sequence[str], None] = "0006_bounded_gmail_scans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SUBSCRIPTION_COLUMNS = (
    sa.Column("interval_unit", sa.String(length=12), nullable=True),
    sa.Column("interval_count", sa.Integer(), nullable=True),
    sa.Column("recurrence_end_at", sa.DateTime(), nullable=True),
    sa.Column("status", sa.String(length=24), server_default="active", nullable=False),
    sa.Column("paused_until", sa.DateTime(), nullable=True),
    sa.Column("cancellation_effective_at", sa.DateTime(), nullable=True),
    sa.Column("amount_type", sa.String(length=16), server_default="fixed", nullable=False),
    sa.Column(
        "spending_type", sa.String(length=16), server_default="unspecified", nullable=False,
    ),
)

DETECTION_COLUMNS = (
    sa.Column("interval_unit", sa.String(length=12), nullable=True),
    sa.Column("interval_count", sa.Integer(), nullable=True),
    sa.Column(
        "cadence_confidence", sa.String(length=16), server_default="medium", nullable=False,
    ),
    sa.Column("cadence_evidence", sa.String(length=300), nullable=True),
    sa.Column("next_due", sa.DateTime(), nullable=True),
    sa.Column(
        "due_date_confidence", sa.String(length=16), server_default="unknown", nullable=False,
    ),
    sa.Column("due_date_evidence", sa.String(length=300), nullable=True),
    sa.Column("amount_type", sa.String(length=16), server_default="fixed", nullable=False),
)

NEW_CATEGORIES = (
    "housing",
    "insurance",
    "phone_internet",
    "education",
    "childcare",
    "debt",
    "memberships",
    "donations",
    "business",
)


def _add_columns(table: str, columns: tuple[sa.Column, ...]) -> None:
    if context.is_offline_mode():
        for column in columns:
            op.add_column(table, column)
        return
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}
    for column in columns:
        if column.name not in existing:
            op.add_column(table, column)


def _expand_category_enum() -> None:
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for value in NEW_CATEGORIES:
        # Values are compile-time constants, never user input.
        op.execute(sa.text(f"ALTER TYPE category ADD VALUE IF NOT EXISTS '{value}'"))


def upgrade() -> None:
    _expand_category_enum()
    _add_columns("subscriptions", SUBSCRIPTION_COLUMNS)
    _add_columns("detected_subscriptions", DETECTION_COLUMNS)
    _add_columns(
        "user_preferences",
        (sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),),
    )

    # Adopt every existing three-value record into the new cadence without
    # changing its financial meaning.
    op.execute(sa.text("""
        UPDATE subscriptions
        SET interval_unit = CASE
                WHEN cycle = 'weekly' THEN 'week'
                WHEN cycle = 'yearly' THEN 'year'
                ELSE 'month'
            END,
            interval_count = 1,
            status = CASE WHEN is_active THEN 'active' ELSE 'cancelled' END
        WHERE interval_unit IS NULL OR interval_count IS NULL
    """))
    op.execute(sa.text("""
        UPDATE detected_subscriptions
        SET interval_unit = CASE
                WHEN cycle = 'weekly' THEN 'week'
                WHEN cycle = 'yearly' THEN 'year'
                ELSE 'month'
            END,
            interval_count = 1,
            cadence_confidence = CASE
                WHEN confidence = 'high' THEN 'high'
                ELSE 'medium'
            END
        WHERE interval_unit IS NULL OR interval_count IS NULL
    """))

    if context.is_offline_mode():
        op.create_index(
            "ix_subscriptions_user_status_due",
            "subscriptions",
            ["user_id", "status", "next_due"],
        )
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("subscriptions")}
    if "ix_subscriptions_user_status_due" not in indexes:
        op.create_index(
            "ix_subscriptions_user_status_due",
            "subscriptions",
            ["user_id", "status", "next_due"],
        )

    if bind.dialect.name == "postgresql":
        checks = {
            item["name"] for item in sa.inspect(bind).get_check_constraints("subscriptions")
        }
        if "ck_subscriptions_cadence_pair" not in checks:
            op.create_check_constraint(
                "ck_subscriptions_cadence_pair",
                "subscriptions",
                "(interval_unit IS NULL AND interval_count IS NULL) OR "
                "(interval_unit IS NOT NULL AND interval_count IS NOT NULL "
                "AND interval_count >= 1 AND interval_count <= 1200)",
            )
        if "ck_subscriptions_interval_unit" not in checks:
            op.create_check_constraint(
                "ck_subscriptions_interval_unit",
                "subscriptions",
                "interval_unit IS NULL OR interval_unit IN ('day', 'week', 'month', 'year')",
            )
        if "ck_subscriptions_status" not in checks:
            op.create_check_constraint(
                "ck_subscriptions_status",
                "subscriptions",
                "status IN ('active', 'paused', 'cancelling', 'cancelled', 'ended')",
            )
        if "ck_subscriptions_amount_type" not in checks:
            op.create_check_constraint(
                "ck_subscriptions_amount_type",
                "subscriptions",
                "amount_type IN ('fixed', 'variable')",
            )
        if "ck_subscriptions_spending_type" not in checks:
            op.create_check_constraint(
                "ck_subscriptions_spending_type",
                "subscriptions",
                "spending_type IN ('unspecified', 'essential', 'optional')",
            )

        detection_checks = {
            item["name"]
            for item in sa.inspect(bind).get_check_constraints("detected_subscriptions")
        }
        if "ck_detected_subscriptions_cadence_pair" not in detection_checks:
            op.create_check_constraint(
                "ck_detected_subscriptions_cadence_pair",
                "detected_subscriptions",
                "(interval_unit IS NULL AND interval_count IS NULL) OR "
                "(interval_unit IS NOT NULL AND interval_count IS NOT NULL "
                "AND interval_count >= 1 AND interval_count <= 1200)",
            )
        if "ck_detected_subscriptions_interval_unit" not in detection_checks:
            op.create_check_constraint(
                "ck_detected_subscriptions_interval_unit",
                "detected_subscriptions",
                "interval_unit IS NULL OR interval_unit IN ('day', 'week', 'month', 'year')",
            )
        if "ck_detected_subscriptions_cadence_confidence" not in detection_checks:
            op.create_check_constraint(
                "ck_detected_subscriptions_cadence_confidence",
                "detected_subscriptions",
                "cadence_confidence IN ('high', 'medium', 'unknown')",
            )
        if "ck_detected_subscriptions_due_confidence" not in detection_checks:
            op.create_check_constraint(
                "ck_detected_subscriptions_due_confidence",
                "detected_subscriptions",
                "due_date_confidence IN ('high', 'medium', 'unknown')",
            )
        if "ck_detected_subscriptions_amount_type" not in detection_checks:
            op.create_check_constraint(
                "ck_detected_subscriptions_amount_type",
                "detected_subscriptions",
                "amount_type IN ('fixed', 'variable')",
            )


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely while rows may reference
    # them, so category expansion is intentionally retained on downgrade.
    op.drop_index("ix_subscriptions_user_status_due", table_name="subscriptions")
    if not context.is_offline_mode() and op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(
            "ck_detected_subscriptions_amount_type",
            "detected_subscriptions",
            type_="check",
        )
        op.drop_constraint(
            "ck_detected_subscriptions_due_confidence",
            "detected_subscriptions",
            type_="check",
        )
        op.drop_constraint(
            "ck_detected_subscriptions_cadence_confidence",
            "detected_subscriptions",
            type_="check",
        )
        op.drop_constraint(
            "ck_detected_subscriptions_interval_unit",
            "detected_subscriptions",
            type_="check",
        )
        op.drop_constraint(
            "ck_detected_subscriptions_cadence_pair",
            "detected_subscriptions",
            type_="check",
        )
        op.drop_constraint(
            "ck_subscriptions_interval_unit", "subscriptions", type_="check"
        )
        op.drop_constraint(
            "ck_subscriptions_spending_type", "subscriptions", type_="check"
        )
        op.drop_constraint(
            "ck_subscriptions_amount_type", "subscriptions", type_="check"
        )
        op.drop_constraint(
            "ck_subscriptions_status", "subscriptions", type_="check"
        )
        op.drop_constraint(
            "ck_subscriptions_cadence_pair", "subscriptions", type_="check"
        )
    bind = op.get_bind() if not context.is_offline_mode() else None
    if bind is not None and bind.dialect.name == "sqlite":
        # A clean recovery database is bootstrapped from current metadata, so
        # SQLite can already have named CHECK constraints that reference these
        # columns. SQLite's direct DROP COLUMN refuses to leave a dangling
        # constraint. Batch recreation removes only constraints introduced by
        # this revision and preserves every legacy column and row.
        inspector = sa.inspect(bind)
        table_specs = (
            (
                "detected_subscriptions",
                DETECTION_COLUMNS,
                {
                    "ck_detected_subscriptions_cadence_pair",
                    "ck_detected_subscriptions_interval_unit",
                    "ck_detected_subscriptions_cadence_confidence",
                    "ck_detected_subscriptions_due_confidence",
                    "ck_detected_subscriptions_amount_type",
                },
            ),
            (
                "subscriptions",
                SUBSCRIPTION_COLUMNS,
                {
                    "ck_subscriptions_cadence_pair",
                    "ck_subscriptions_interval_unit",
                    "ck_subscriptions_status",
                    "ck_subscriptions_amount_type",
                    "ck_subscriptions_spending_type",
                },
            ),
        )
        for table_name, columns, owned_checks in table_specs:
            existing_columns = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            existing_checks = {
                check["name"]
                for check in inspector.get_check_constraints(table_name)
                if check.get("name")
            }
            with op.batch_alter_table(table_name) as batch_op:
                for name in sorted(existing_checks & owned_checks):
                    batch_op.drop_constraint(name, type_="check")
                for column in reversed(columns):
                    if column.name in existing_columns:
                        batch_op.drop_column(column.name)
        preference_columns = {
            column["name"] for column in inspector.get_columns("user_preferences")
        }
        if "timezone" in preference_columns:
            with op.batch_alter_table("user_preferences") as batch_op:
                batch_op.drop_column("timezone")
        return

    op.drop_column("user_preferences", "timezone")
    for column in reversed(DETECTION_COLUMNS):
        op.drop_column("detected_subscriptions", column.name)
    for column in reversed(SUBSCRIPTION_COLUMNS):
        op.drop_column("subscriptions", column.name)
