"""Background worker that consumes AI summary jobs and persists results."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import Any, cast

from redis.asyncio import Redis
from shared import cache_async as shared_cache
from shared.logging import log_event, reset_request_id, set_request_id
from shared.repository import apply_market_summary
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .database import session_scope
from .logging_config import setup_logging
from .metrics import SUMMARY_DLQ_COUNTER
from .summary_client import SummaryClient, SummaryClientError
from .summary_jobs import SummaryJob

setup_logging("reveal_market.summary_worker")
logger = logging.getLogger("reveal_market.summary_worker")
settings = get_settings()


def _get_redis_client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def _pop_job(redis_client: Redis) -> SummaryJob | None:
    result = await cast(
        Awaitable[tuple[str, str | bytes] | None],
        redis_client.brpop([settings.summary_queue_key], timeout=int(settings.summary_queue_poll_seconds)),
    )
    if result is None:
        return None
    _, raw = cast(tuple[str, str | bytes], result)
    payload = raw if isinstance(raw, str) else raw.decode("utf-8")
    job = SummaryJob.from_json(payload)
    log_event(
        logger,
        logging.INFO,
        event="worker.summary.job_received",
        message="pulled summary job from queue",
        job_id=job.job_id,
        event_id=job.event_id,
    )
    return job


async def _ack_success(redis_client: Redis, job: SummaryJob, summary_text: str) -> None:
    log_event(
        logger,
        logging.INFO,
        event="worker.summary.completed",
        message="stored AI summary",
        event_id=job.event_id,
        job_id=job.job_id,
        attempts=job.attempts,
        characters=len(summary_text),
    )
    await shared_cache.invalidate_tag(redis_client, f"market:{job.event_id}")
    await shared_cache.invalidate_tag(redis_client, "markets:list")


async def _handle_failure(redis_client: Redis, job: SummaryJob, reason: str) -> None:
    job.attempts += 1
    if job.attempts >= settings.summary_retry_max_attempts:
        await cast(Awaitable[Any], redis_client.lpush(settings.summary_dead_letter_key, job.to_json()))
        log_event(
            logger,
            logging.ERROR,
            event="worker.summary.dead_letter",
            message="summary job moved to dead letter queue",
            event_id=job.event_id,
            job_id=job.job_id,
            attempts=job.attempts,
            reason=reason,
            dlq_depth=await cast(Awaitable[int], redis_client.llen(settings.summary_dead_letter_key)),
        )
        try:
            SUMMARY_DLQ_COUNTER.labels(outcome="dead_letter").inc()
        except Exception as exc:  # pragma: no cover - metrics guard
            log_event(
                logger,
                logging.DEBUG,
                event="worker.summary.dlq_metric_failed",
                message="failed to increment DLQ metric",
                error=str(exc),
            )
    else:
        await cast(Awaitable[Any], redis_client.rpush(settings.summary_queue_key, job.to_json()))
        log_event(
            logger,
            logging.WARNING,
            event="worker.summary.requeued",
            message="summary job re-queued after failure",
            event_id=job.event_id,
            job_id=job.job_id,
            attempts=job.attempts,
            reason=reason,
        )


async def run_summary_worker() -> None:
    if not settings.summary_enabled:
        log_event(
            logger,
            logging.WARNING,
            event="worker.summary.disabled",
            message="summary worker disabled via configuration",
        )
        return
    redis_client = _get_redis_client()
    client = SummaryClient()
    log_event(
        logger,
        logging.INFO,
        event="worker.summary.start",
        message="summary worker started",
        queue=settings.summary_queue_key,
    )
    while True:
        job = await _pop_job(redis_client)
        if job is None:
            continue
        await process_job(job, redis_client, client)


async def process_job(job: SummaryJob, redis_client: Redis, client: SummaryClient) -> bool:
    """Process a single summary job; return True on success."""

    token = set_request_id(job.job_id)
    try:
        if not settings.summary_enabled:
            log_event(
                logger,
                logging.DEBUG,
                event="worker.summary.skip_disabled",
                message="skipping summary job because summaries are disabled",
                job_id=job.job_id,
                event_id=job.event_id,
            )
            return False

        log_event(
            logger,
            logging.INFO,
            event="worker.summary.processing",
            message="processing summary job",
            job_id=job.job_id,
            event_id=job.event_id,
            attempts=job.attempts,
        )
        try:
            result = await client.generate(job)
        except SummaryClientError as exc:
            await _handle_failure(redis_client, job, str(exc))
            return False

        async with session_scope() as session:
            await _apply_summary(session, job, result)
        await _ack_success(redis_client, job, result.text)
        return True
    finally:
        reset_request_id(token)


async def _apply_summary(session: AsyncSession, job: SummaryJob, result) -> None:
    await session.run_sync(
        apply_market_summary,
        job.event_id,
        summary=result.text,
        source=result.source,
        model=result.model,
        metadata=result.metadata,
        checked_at=result.generated_at,
    )


def main() -> None:  # pragma: no cover - CLI entrypoint
    try:
        asyncio.run(run_summary_worker())
    except KeyboardInterrupt:
        logger.info("summary worker interrupted, shutting down")


if __name__ == "__main__":  # pragma: no cover
    main()
