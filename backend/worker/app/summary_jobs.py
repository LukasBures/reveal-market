from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from redis import Redis
from shared.logging import log_event

from .config import get_settings
from .polymarket import MarketPayload

logger = logging.getLogger("reveal_market.worker.summary")
settings = get_settings()


@dataclass
class SummaryJob:
    job_id: str
    event_id: str
    title: str
    description: str
    category: str | None
    tags: list[str]
    oracle: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_json(self) -> str:
        payload = {
            "job_id": self.job_id,
            "event_id": self.event_id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "oracle": self.oracle,
            "metadata": self.metadata,
            "attempts": self.attempts,
            "requested_at": self.requested_at.isoformat(),
        }
        return json.dumps(payload)

    @classmethod
    def from_json(cls, raw: str) -> SummaryJob:
        data = json.loads(raw)
        requested_at_str = data.get("requested_at")
        requested_at = (
            datetime.fromisoformat(requested_at_str) if isinstance(requested_at_str, str) else datetime.now(UTC)
        )
        return cls(
            job_id=data["job_id"],
            event_id=data["event_id"],
            title=data["title"],
            description=data["description"],
            category=data.get("category"),
            tags=list(data.get("tags") or []),
            oracle=data.get("oracle"),
            metadata=dict(data.get("metadata") or {}),
            attempts=int(data.get("attempts") or 0),
            requested_at=requested_at,
        )


def maybe_enqueue_summary_job(
    redis_client: Redis | None,
    *,
    market_record,
    market_payload: MarketPayload,
) -> bool:
    """Queue a summary enrichment job when the market lacks a fresh AI narrative."""

    if redis_client is None or not settings.summary_enabled:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.summary.skip_disabled",
            message="summary enrichment disabled or redis unavailable",
            event_id=getattr(market_record, "event_id", None),
            summary_enabled=settings.summary_enabled,
        )
        return False

    description = _extract_description(
        getattr(market_payload, "description", None),
        market_payload.gamma_metadata,
    )
    if not description:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.summary.skip_no_description",
            message="market missing description; skipping summary job",
            event_id=market_record.event_id,
        )
        return False

    now = datetime.now(UTC)
    needs_summary, reason = _needs_summary(market_record, now)
    if not needs_summary:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.summary.skip_fresh",
            message="market summary is still fresh",
            event_id=market_record.event_id,
            reason=reason,
        )
        return False
    inflight, age_seconds = _request_inflight(market_record, now)
    if inflight:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.summary.skip_inflight",
            message="summary request already in-flight",
            event_id=market_record.event_id,
            age_seconds=age_seconds,
        )
        return False

    job = SummaryJob(
        job_id=str(uuid4()),
        event_id=market_record.event_id,
        title=market_record.title,
        description=description,
        category=getattr(market_record, "category", None),
        tags=list(getattr(market_record, "tags", []) or []),
        oracle=getattr(market_record, "oracle", None),
        metadata=_build_metadata(market_payload),
    )
    redis_client.lpush(settings.summary_queue_key, job.to_json())
    market_record.summary_requested_at = now
    if logger.isEnabledFor(logging.DEBUG):
        log_event(
            logger,
            logging.DEBUG,
            event="worker.summary.enqueued",
            message="queued market for AI summary enrichment",
            event_id=market_record.event_id,
            job_id=job.job_id,
        )
    return True


def _needs_summary(market_record, now: datetime) -> tuple[bool, str]:
    summary = getattr(market_record, "summary", None)
    if not summary:
        return True, "summary_missing"
    checked_at = getattr(market_record, "summary_checked_at", None)
    if checked_at is None:
        return True, "summary_time_unknown"
    age = (now - checked_at).total_seconds()
    if age >= settings.summary_refresh_interval_seconds:
        return True, "summary_stale"
    return False, "summary_fresh"


def _request_inflight(market_record, now: datetime) -> tuple[bool, float | None]:
    requested_at = getattr(market_record, "summary_requested_at", None)
    if requested_at is None:
        return False, None
    age = (now - requested_at).total_seconds()
    return age < settings.summary_requested_ttl_seconds, age


def _extract_description(description: str | None, gamma_metadata: Mapping[str, Any] | None) -> str | None:
    candidate = description or (gamma_metadata.get("description") if isinstance(gamma_metadata, Mapping) else None)
    if isinstance(candidate, str):
        candidate = candidate.strip()
    return candidate or None


def _build_metadata(market_payload: MarketPayload) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if market_payload.gamma_metadata:
        metadata["gamma_metadata"] = market_payload.gamma_metadata
    if market_payload.outcomes:
        metadata["outcomes"] = market_payload.outcomes
    if market_payload.tags:
        metadata["tags"] = market_payload.tags
    if market_payload.source_updated_at:
        metadata["source_updated_at"] = market_payload.source_updated_at.isoformat()
    if market_payload.content_hash:
        metadata["content_hash"] = market_payload.content_hash
    return metadata
