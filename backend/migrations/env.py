from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from shared.models import Base  # noqa: E402

config = context.config

# Only apply Alembic's fileConfig if caller asked for it. We set
# `configure_logger=False` when invoking migrations so app logging stays unified.
if config.attributes.get("configure_logger", True) and config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = context.get_x_argument(as_dictionary=True).get("db_url") or config.get_main_option("sqlalchemy.url")
    if not url:
        url = os.getenv("RM_DATABASE_URL", "")
        if not url:
            raise RuntimeError("RM_DATABASE_URL is required for migrations (set env var or pass --x db_url=...)")
        config.set_main_option("sqlalchemy.url", url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    if not configuration.get("sqlalchemy.url"):
        db_url = os.getenv("RM_DATABASE_URL", "")
        if not db_url:
            raise RuntimeError("RM_DATABASE_URL is required for migrations")
        configuration["sqlalchemy.url"] = db_url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
