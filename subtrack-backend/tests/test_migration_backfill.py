import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class FlexibleCadenceMigrationTests(unittest.TestCase):
    def alembic(self, database_url: str, *arguments: str) -> None:
        environment = {
            **os.environ,
            "DATABASE_URL": database_url,
            "SUPABASE_JWT_SECRET": "migration-test-secret",
            "ANTHROPIC_API_KEY": "migration-test-key",
            "ENVIRONMENT": "development",
        }
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
            cwd=BACKEND_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if completed.returncode:
            self.fail(
                f"Alembic {' '.join(arguments)} failed:\n"
                f"{completed.stdout}\n{completed.stderr}"
            )

    def deploy_migrate(self, database_url: str) -> None:
        environment = {
            **os.environ,
            "DATABASE_URL": database_url,
            "SUPABASE_JWT_SECRET": "migration-test-secret",
            "ANTHROPIC_API_KEY": "migration-test-key",
            "ENVIRONMENT": "development",
        }
        completed = subprocess.run(
            [sys.executable, "scripts/migrate.py"],
            cwd=BACKEND_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if completed.returncode:
            self.fail(
                "Production migration command failed:\n"
                f"{completed.stdout}\n{completed.stderr}"
            )

    def test_exact_deploy_command_bootstraps_blank_database_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blank.sqlite3"
            database_url = f"sqlite:///{path}"

            self.deploy_migrate(database_url)
            self.deploy_migrate(database_url)

            with sqlite3.connect(path) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT version_num FROM alembic_version"
                    ).fetchone(),
                    ("0011_query_indexes",),
                )
                message_indexes = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA index_list(agent_messages)"
                    ).fetchall()
                }
                self.assertIn("ix_agent_messages_status_updated", message_indexes)
                self.assertIn("ix_agent_messages_user_role_created", message_indexes)

            # A clean recovery database starts from current ORM metadata, which
            # includes named SQLite CHECK constraints. The supported rollback
            # must remove those constraints before dropping cadence columns.
            self.alembic(database_url, "downgrade", "0006_bounded_gmail_scans")
            self.alembic(database_url, "upgrade", "head")
            with sqlite3.connect(path) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT version_num FROM alembic_version"
                    ).fetchone(),
                    ("0011_query_indexes",),
                )

    def test_legacy_rows_backfill_and_survive_supported_downgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            database_url = f"sqlite:///{path}"
            with sqlite3.connect(path) as connection:
                connection.executescript("""
                    CREATE TABLE subscriptions (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        cycle TEXT NOT NULL,
                        is_active BOOLEAN NOT NULL,
                        next_due DATETIME
                    );
                    CREATE TABLE detected_subscriptions (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        cycle TEXT NOT NULL,
                        confidence TEXT NOT NULL
                    );
                    CREATE TABLE user_preferences (
                        user_id TEXT PRIMARY KEY
                    );
                    INSERT INTO subscriptions VALUES
                        ('weekly-active', 'owner', 'weekly', 1, NULL),
                        ('yearly-inactive', 'owner', 'yearly', 0, NULL);
                    INSERT INTO detected_subscriptions VALUES
                        ('monthly-detection', 'owner', 'monthly', 'high');
                    INSERT INTO user_preferences VALUES ('owner');
                """)

            # These recurring-payment tables predate Alembic. Production is
            # already stamped at 0006, so the test starts from that exact
            # deployment boundary rather than inventing a clean-install path.
            self.alembic(database_url, "stamp", "0006_bounded_gmail_scans")
            self.alembic(database_url, "upgrade", "head")

            with sqlite3.connect(path) as connection:
                self.assertIsNotNone(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table' "
                        "AND name = 'duplicate_dismissals'"
                    ).fetchone()
                )
                duplicate_indexes = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA index_list(duplicate_dismissals)"
                    ).fetchall()
                }
                self.assertIn(
                    "ix_duplicate_dismissals_subscription_a",
                    duplicate_indexes,
                )
                self.assertIn(
                    "ix_duplicate_dismissals_subscription_b",
                    duplicate_indexes,
                )
                weekly = connection.execute(
                    "SELECT interval_unit, interval_count, status FROM subscriptions "
                    "WHERE id = 'weekly-active'"
                ).fetchone()
                yearly = connection.execute(
                    "SELECT interval_unit, interval_count, status FROM subscriptions "
                    "WHERE id = 'yearly-inactive'"
                ).fetchone()
                detected = connection.execute(
                    "SELECT interval_unit, interval_count, cadence_confidence "
                    "FROM detected_subscriptions WHERE id = 'monthly-detection'"
                ).fetchone()
                self.assertEqual(weekly, ("week", 1, "active"))
                self.assertEqual(yearly, ("year", 1, "cancelled"))
                self.assertEqual(detected, ("month", 1, "high"))

                # An old binary may still write only the compatibility cycle
                # during a rolling deploy. The nullable cadence pair and
                # discriminator preserve that row for the new fallback path.
                connection.execute(
                    "INSERT INTO detected_subscriptions "
                    "(id, user_id, cycle, confidence) VALUES (?, ?, ?, ?)",
                    ("rolling-old-write", "owner", "yearly", "medium"),
                )
                rolling = connection.execute(
                    "SELECT interval_unit, interval_count, cadence_confidence "
                    "FROM detected_subscriptions WHERE id = 'rolling-old-write'"
                ).fetchone()
                self.assertEqual(rolling, (None, None, "medium"))

            self.alembic(database_url, "downgrade", "0006_bounded_gmail_scans")
            with sqlite3.connect(path) as connection:
                subscription_columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(subscriptions)"
                    ).fetchall()
                }
                self.assertNotIn("interval_unit", subscription_columns)
                self.assertIsNone(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table' "
                        "AND name = 'duplicate_dismissals'"
                    ).fetchone()
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT cycle, is_active FROM subscriptions "
                        "WHERE id = 'weekly-active'"
                    ).fetchone(),
                    ("weekly", 1),
                )


if __name__ == "__main__":
    unittest.main()
