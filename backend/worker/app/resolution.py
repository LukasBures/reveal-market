# ruff: noqa: UP047
"""Resolution fetching and persistence helpers (Goldsky/Conditional Tokens)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

import httpx
from shared import models as shared_models
from shared import repository_async as shared_repository
from shared.logging import log_event
from shared.models import MarketStatusEnum
from shared.onchain.conditional_tokens import _derive_winners
from sqlalchemy.ext.asyncio import AsyncSession

from . import runtime
from .polymarket import MarketPayload

logger = runtime.logger
goldsky_client = runtime.goldsky_client
conditional_tokens_client = runtime.conditional_tokens_client

T = TypeVar("T")


@dataclass
class ResolutionOutcome:
    changed: bool = False
    condition_id: str | None = None
    cache_payload: dict[str, Any] | None = None


async def _run_with_retries(
    action: Callable[[], Awaitable[T]],
    max_attempts: int,
    base_backoff: float,
    max_backoff: float | None = None,
    on_retry: Callable[[int, BaseException | None], Awaitable[None] | None] | None = None,
) -> T:  # noqa: UP047
    """Execute an async action with optional retry semantics using tenacity."""

    if max_attempts <= 1:
        return await action()

    try:
        from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential
    except ModuleNotFoundError:  # pragma: no cover - tenacity optional
        return await action()

    base_delay = base_backoff if base_backoff > 0 else 0.1
    wait_kwargs = {"multiplier": base_delay, "min": base_delay}
    if max_backoff is not None and max_backoff > 0:
        wait_kwargs["max"] = max_backoff

    async def _before_sleep(retry_state):
        if on_retry is None:
            return
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        try:
            maybe_awaitable = on_retry(retry_state.attempt_number, exc)
            if asyncio.iscoroutine(maybe_awaitable):
                await maybe_awaitable
        except Exception:  # pragma: no cover - logging must not break retries
            logger.debug(
                "retry callback raised",
                extra={"attempt": retry_state.attempt_number, "error": str(exc) if exc else None},
            )

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(**wait_kwargs),
        retry=retry_if_exception_type(Exception),
        before_sleep=_before_sleep,
        reraise=True,
    ):
        with attempt:
            return await action()
    raise RuntimeError("async retryer exited unexpectedly")


def _should_refresh_resolution(existing, now: datetime) -> bool:
    if existing is None:
        return True
    if not existing.resolved:
        return True
    if existing.checked_at is None:
        return True
    return (now - existing.checked_at).total_seconds() >= runtime.settings.resolution_refresh_interval_seconds


def _parse_checked_at(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return fallback
    return fallback


def _build_resolution_record(
    summary: dict[str, Any],
    market: MarketPayload,
    checked_at: datetime,
    db_market: Any | None = None,
) -> dict[str, Any]:
    outcomes = summary.get("outcomes") or (market.outcomes or [])
    payouts = summary.get("payouts") or []
    winners = summary.get("winners") or []
    if not winners:
        winners = summary.get("winners") or _derive_winners(payouts, outcomes)
    winning_outcome = summary.get("winningOutcomeId") or summary.get("winning_outcome_id")
    if winning_outcome is None and winners:
        try:
            winning_outcome = winners[0].get("index")
        except Exception:
            winning_outcome = None
    return {
        "condition_id": summary.get("condition_id") or summary.get("conditionId"),
        "source": summary.get("source", "conditional_tokens"),
        "resolved": bool(summary.get("resolved")),
        "payouts": payouts,
        "winners": winners,
        "outcomes": outcomes,
        "oracle": summary.get("oracle"),
        "question_id": summary.get("questionId"),
        "transaction_hash": summary.get("transactionHash"),
        "block_number": summary.get("blockNumber"),
        "block_timestamp": summary.get("blockTimestamp"),
        "winning_outcome_id": winning_outcome,
        "rake_bps": summary.get("rakeBps") or getattr(market, "rake_bps", None),
        "request_id": summary.get("request_id") or summary.get("requestId"),
        "market_id": getattr(db_market, "id", None),
        "event_id": getattr(db_market, "event_id", None) or market.event_id,
        "checked_at": checked_at,
    }


async def _fetch_resolution_snapshot(
    condition_id: str,
    market: MarketPayload,
    outcome_count_hint: int | None,
) -> dict[str, Any] | None:
    """Return the best-effort resolution summary from Goldsky or fallback RPC."""
    outcomes = market.outcomes or []
    attempts = runtime.settings.resolution_fetch_max_attempts
    backoff = runtime.settings.resolution_fetch_backoff_seconds
    backoff_max = runtime.settings.resolution_fetch_backoff_max_seconds

    async def _with_retry(action: Callable[[], Awaitable[dict[str, Any] | None]], source: str) -> dict[str, Any] | None:
        async def _log_retry(attempt: int, exc: BaseException | None) -> None:
            log_event(
                logger,
                logging.WARNING,
                event="worker.resolution.retry",
                message="retrying resolution fetch",
                source=source,
                attempt=attempt,
                max_attempts=attempts,
                error=str(exc) if exc else None,
            )

        try:
            return await _run_with_retries(
                action,
                attempts,
                backoff,
                backoff_max,
                on_retry=_log_retry if attempts > 1 else None,
            )
        except (httpx.HTTPError, httpx.RequestError, RuntimeError, ValueError) as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.WARNING,
                event=f"worker.resolution.{source}_failed",
                message="failed to load resolution",
                condition_id=condition_id,
                error=str(exc),
            )
            return None

    goldsky = goldsky_client or runtime.goldsky_client
    if goldsky is not None:

        async def _goldsky_action() -> dict[str, Any] | None:
            result = goldsky.resolution_summary(condition_id, outcomes, outcome_count_hint)  # type: ignore[call-arg]
            if asyncio.iscoroutine(result):
                return await result  # type: ignore[return-value]
            return result  # type: ignore[return-value]

        summary = await _with_retry(_goldsky_action, "goldsky")
        if summary:
            log_event(
                logger,
                logging.DEBUG,
                event="worker.resolution.goldsky_success",
                message="loaded resolution from goldsky",
                condition_id=condition_id,
                resolved=summary.get("resolved"),
            )
            return summary
    conditional = conditional_tokens_client or runtime.conditional_tokens_client
    if conditional is None:
        return None
    return await _with_retry(
        lambda: asyncio.to_thread(conditional.resolution_summary, condition_id, outcomes, outcome_count_hint),
        "conditional_tokens",
    )


async def apply_resolution(
    session: AsyncSession, db_market: shared_models.Market | None, market: MarketPayload
) -> ResolutionOutcome:
    condition_id = market.condition_id
    active_goldsky = goldsky_client or runtime.goldsky_client
    active_conditional = conditional_tokens_client or runtime.conditional_tokens_client
    if (
        (active_goldsky is None and active_conditional is None)
        or not isinstance(condition_id, str)
        or not condition_id.startswith("0x")
    ):
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                event="worker.resolution.skipped_unavailable",
                message="skipping resolution sync because prerequisites not met",
                condition_id=condition_id,
                goldsky_enabled=active_goldsky is not None,
                conditional_tokens_enabled=active_conditional is not None,
            )
        return ResolutionOutcome()

    if db_market is None:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.resolution.skipped_missing_market",
            message="cannot apply resolution without a persisted market record",
            condition_id=condition_id,
        )
        return ResolutionOutcome()

    # db_market is guaranteed from here for typing
    assert db_market is not None

    normalized_condition_id = condition_id.lower()
    outcome_count_hint = len(market.outcome_prices) if market.outcome_prices else None
    existing = await shared_repository.get_resolution_by_condition_id(session, normalized_condition_id)
    now = datetime.now(UTC)

    if not _should_refresh_resolution(existing, now):
        if logger.isEnabledFor(logging.DEBUG):
            last_checked = getattr(existing, "checked_at", None)
            log_event(
                logger,
                logging.DEBUG,
                event="worker.resolution.skip_refresh",
                message="existing resolution snapshot still within freshness window",
                condition_id=normalized_condition_id,
                last_checked=last_checked.isoformat() if last_checked else None,
                resolved=getattr(existing, "resolved", None),
            )
        return ResolutionOutcome()

    summary = await _fetch_resolution_snapshot(normalized_condition_id, market, outcome_count_hint)
    if summary is None:
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                event="worker.resolution.snapshot_missing",
                message="resolution snapshot could not be loaded",
                condition_id=normalized_condition_id,
            )
        return ResolutionOutcome()

    checked_at_dt = _parse_checked_at(summary.get("checkedAt"), now)
    record_payload = _build_resolution_record(summary, market, checked_at_dt, db_market=db_market)
    record_payload["condition_id"] = normalized_condition_id

    if record_payload["resolved"] and (
        record_payload.get("transaction_hash") is None or record_payload.get("block_number") is None
    ):
        log_event(
            logger,
            logging.WARNING,
            event="worker.resolution.partial_payload",
            message="resolution payload missing block metadata",
            condition_id=normalized_condition_id,
            tx_hash=record_payload.get("transaction_hash"),
            block_number=record_payload.get("block_number"),
        )

    await shared_repository.upsert_resolution(session, record_payload)
    cache_payload = {
        **record_payload,
        "checkedAt": checked_at_dt.isoformat(),
    }
    block_ts = cache_payload.get("block_timestamp")
    if isinstance(block_ts, datetime):
        cache_payload["block_timestamp"] = block_ts.isoformat()

    log_event(
        logger,
        logging.DEBUG,
        event="worker.resolution.persisted",
        message="persisted conditional tokens resolution snapshot",
        condition_id=normalized_condition_id,
        resolved=record_payload["resolved"],
        block_number=record_payload["block_number"],
    )

    if record_payload["resolved"]:
        db_market.status = MarketStatusEnum.SETTLED.value
        if getattr(db_market, "closed", None) is not True:
            db_market.closed = True
        db_market.resolved_at = checked_at_dt
        session.add(db_market)
        log_event(
            logger,
            logging.DEBUG,
            event="worker.resolution.detected",
            message="polymarket resolution detected",
            condition_id=normalized_condition_id,
            winners=record_payload["winners"],
            block_number=record_payload["block_number"],
        )
    else:
        db_market.resolved_at = None
        session.add(db_market)
    return ResolutionOutcome(
        changed=True,
        condition_id=normalized_condition_id,
        cache_payload=cache_payload,
    )
