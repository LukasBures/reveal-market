from __future__ import annotations

from pathlib import Path

def _migrations_root() -> Path:
    root = Path(__file__).resolve().parents[1] / "migrations"
    if not root.exists():
        raise RuntimeError("Unable to locate migrations directory")
    return root


def run_migrations(database_url: str) -> None:
    """Apply Alembic migrations using the provided database URL."""

    from alembic import command
    from alembic.config import Config

    migrations_root = _migrations_root()
    config = Config(str(migrations_root / "alembic.ini"))
    config.set_main_option("script_location", str(migrations_root))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
