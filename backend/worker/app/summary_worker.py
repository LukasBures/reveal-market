from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from redis import Redis
from shared import cache as shared_cache
from shared.logging import log_event, reset_request_id, set_request_id
from shared.repository import apply_market_summary
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .logging_config import setup_logging
from .summary_client import SummaryClient, SummaryClientError
from .summary_jobs import SummaryJob

setup_logging("reveal_market.summary_worker")
logger = logging.getLogger("reveal_market.summary_worker")
settings = get_settings()

engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _get_redis_client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def _pop_job(redis_client: Redis) -> SummaryJob | None:
    result = redis_client.brpop(settings.summary_queue_key, timeout=int(settings.summary_queue_poll_seconds))
    if result is None:
        return None
    _, raw = result
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


def _ack_success(redis_client: Redis, job: SummaryJob, summary_text: str) -> None:
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
    shared_cache.invalidate_tag(redis_client, f"market:{job.event_id}")
    shared_cache.invalidate_tag(redis_client, "markets:list")


def _handle_failure(redis_client: Redis, job: SummaryJob, reason: str) -> None:
    job.attempts += 1
    if job.attempts >= settings.summary_retry_max_attempts:
        redis_client.lpush(settings.summary_dead_letter_key, job.to_json())
        log_event(
            logger,
            logging.ERROR,
            event="worker.summary.dead_letter",
            message="summary job moved to dead letter queue",
            event_id=job.event_id,
            job_id=job.job_id,
            attempts=job.attempts,
            reason=reason,
            dlq_depth=redis_client.llen(settings.summary_dead_letter_key),
        )
        try:
            from app.main import SUMMARY_DLQ_COUNTER

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
        redis_client.rpush(settings.summary_queue_key, job.to_json())
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


def run_summary_worker() -> None:
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
        job = _pop_job(redis_client)
        if job is None:
            continue
        process_job(job, redis_client, client)


def process_job(job: SummaryJob, redis_client: Redis, client: SummaryClient) -> bool:
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
            result = client.generate(job)
        except SummaryClientError as exc:
            _handle_failure(redis_client, job, str(exc))
            return False

        with session_scope() as session:
            apply_market_summary(
                session,
                job.event_id,
                summary=result.text,
                source=result.source,
                model=result.model,
                metadata=result.metadata,
                checked_at=result.generated_at,
            )
        _ack_success(redis_client, job, result.text)
        return True
    finally:
        reset_request_id(token)


def main() -> None:  # pragma: no cover - CLI entrypoint
    try:
        run_summary_worker()
    except KeyboardInterrupt:
        logger.info("summary worker interrupted, shutting down")


if __name__ == "__main__":  # pragma: no cover
    main()
