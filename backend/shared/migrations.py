from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import create_engine, text

logger = logging.getLogger("reveal_market.migrations")


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
    from alembic.util.exc import CommandError

    config = _build_alembic_config(database_url)
    config.attributes["configure_logger"] = False
    try:
        command.upgrade(config, "head")
    except CommandError as exc:
        if _is_missing_revision_error(exc) and _allow_reset_on_missing_revision():
            logger.warning(
                "Missing Alembic revision; resetting schema before applying baseline",
                extra={"event": "migrations.missing_revision_reset"},
            )
            _reset_schema(database_url)
            command.upgrade(config, "head")
            return
        raise


def get_current_revision(database_url: str) -> str | None:
    """Return the Alembic revision currently recorded in the database."""

    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            result = connection.execute(text("select version_num from alembic_version"))
            row = result.first()
            return str(row[0]) if row else None
    finally:
        engine.dispose()


def get_head_revision() -> str | None:
    """Return the head revision as defined by the local migrations directory."""

    from alembic.script import ScriptDirectory

    config = _build_alembic_config()
    script = ScriptDirectory.from_config(config)
    return script.get_current_head()


def _is_missing_revision_error(exc: Exception) -> bool:
    message = str(exc)
    return "Can't locate revision identified by" in message or "No such revision" in message


def _allow_reset_on_missing_revision() -> bool:
    flag = os.getenv("RM_MIGRATIONS_ALLOW_RESET")
    if flag is not None:
        return flag.strip().lower() in {"1", "true", "yes"}
    return os.getenv("RM_ENVIRONMENT", "").strip().lower() == "local"


def _reset_schema(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            connection = connection.execution_options(isolation_level="AUTOCOMMIT")
            dialect = engine.dialect.name
            if dialect == "postgresql":
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
            else:
                from sqlalchemy import MetaData

                metadata = MetaData()
                metadata.reflect(bind=connection)
                metadata.drop_all(bind=connection)
    finally:
        engine.dispose()
