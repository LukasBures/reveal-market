from __future__ import annotations

import logging
from dataclasses import dataclass

from redis.asyncio import Redis
from shared import cache_async as shared_cache
from shared import repository_async as shared_repository
from shared.logging import log_event
from shared.migrations import get_current_revision
from shared.migrations import run_migrations as apply_migrations

from . import runtime
from .database import session_scope

logger = runtime.logger
_schema_checked = False


@dataclass
class SchemaSyncResult:
    changed: bool = False
    previous_revision: str | None = None
    current_revision: str | None = None


async def ensure_schema() -> SchemaSyncResult:
    """Apply database migrations once per worker lifecycle if configured."""

    global _schema_checked
    result = SchemaSyncResult()
    if _schema_checked:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.schema.already_checked",
            message="schema state already verified earlier in lifecycle",
            run_migrations=runtime.settings.run_migrations_on_startup,
        )
        return result
    if not runtime.settings.run_migrations_on_startup:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.schema.migrations_disabled",
            message="skipping schema migrations due to configuration",
        )
        return result
    try:
        apply_migrations(runtime.settings.database_url)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.ERROR,
            event="worker.schema.migration_failed",
            message="alembic migrations failed to apply",
            error=str(exc),
        )
        raise
    revision = get_current_revision(runtime.settings.database_url)
    if revision is None:
        log_event(
            logger,
            logging.WARNING,
            event="worker.schema.untracked",
            message="applied migrations but could not resolve Alembic revision",
        )
    else:
        async with session_scope() as session:
            previous_revision = await shared_repository.record_schema_version(session, revision)
        result.current_revision = revision
        result.previous_revision = previous_revision
        result.changed = previous_revision != revision
        log_event(
            logger,
            logging.DEBUG,
            event="worker.schema.synced",
            message="applied migrations and recorded schema revision",
            revision=revision,
            previous_revision=previous_revision,
        )
    _schema_checked = True
    return result


async def propagate_schema_revision(redis_client: Redis | None, state: SchemaSyncResult) -> None:
    """Publish the current schema revision for cache tagging + invalidate stale tags."""

    if redis_client is None or state.current_revision is None:
        return
    try:
        await redis_client.set(runtime.settings.schema_version_key, state.current_revision)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.schema.version_cache_error",
            message="failed to write schema revision cache key",
            error=str(exc),
        )
        return

    log_event(
        logger,
        logging.DEBUG,
        event="worker.schema.version_cached",
        message="published schema revision for cache tagging",
        revision=state.current_revision,
        changed=state.changed,
    )

    if state.changed:
        previous_tag = f"schema:{state.previous_revision}" if state.previous_revision else None
        tags_to_invalidate = ["schema:unknown"]
        if previous_tag:
            tags_to_invalidate.append(previous_tag)
        for tag in tags_to_invalidate:
            invalidated = await shared_cache.invalidate_tag(redis_client, tag)
            log_event(
                logger,
                logging.DEBUG,
                event="worker.schema.cache_reset",
                message="invalidated schema-tagged cache entries",
                tag=tag,
                keys=invalidated,
            )
