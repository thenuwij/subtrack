"""Bootstrap the pre-Alembic tables, then bring the schema to migration head.

Subtrack's recurring-payment tables existed before migrations were introduced.
The migrations deliberately adopt tables that already exist, so this command is
safe for both the original production database and a completely empty recovery
database. It runs once during deployment, never in every web worker.
"""
from pathlib import Path
import sys

from alembic import command
from alembic.config import Config

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base, engine  # noqa: E402
import app.models  # noqa: E402,F401  # register every model with Base.metadata


def main() -> None:
    Base.metadata.create_all(bind=engine)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
