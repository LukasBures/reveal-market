from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, text


def _migrations_root() -> Path:
    root = Path(__file__).resolve().parents[1] / "migrations"
    if not root.exists():
        raise RuntimeError("Unable to locate migrations directory")
    return root


def _build_alembic_config(database_url: str | None = None):
    from alembic.config import Config

    migrations_root = _migrations_root()
    config = Config(str(migrations_root / "alembic.ini"))
    config.set_main_option("script_location", str(migrations_root))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


def run_migrations(database_url: str) -> None:
    """Apply Alembic migrations using the provided database URL."""

    from alembic import command

    config = _build_alembic_config(database_url)
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")


def get_current_revision(database_url: str) -> Optional[str]:
    """Return the Alembic revision currently recorded in the database."""

    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            result = connection.execute(text("select version_num from alembic_version"))
            row = result.first()
            return str(row[0]) if row else None
    finally:
        engine.dispose()


def get_head_revision() -> Optional[str]:
    """Return the head revision as defined by the local migrations directory."""

    from alembic.script import ScriptDirectory

    config = _build_alembic_config()
    script = ScriptDirectory.from_config(config)
    return script.get_current_head()
