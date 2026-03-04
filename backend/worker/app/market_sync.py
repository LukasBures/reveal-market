"""Market persistence helpers: upserts, retention, and resolution backfills."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from redis.asyncio import Redis
from shared import models as shared_models
from shared import repository_async as shared_repository
from shared.logging import log_event
from sqlalchemy import delete, func, inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.state import InstanceState

from . import runtime
from .metrics import record_retention_metrics
from .polymarket import (
    MarketPayload,
    _build_market_hash_payload,
    _compute_market_hash,
    _parse_group_threshold,
)
from .resolution import apply_resolution
from .settlement import _upsert_settlement_from_chain, settlement_needs_refresh

logger = runtime.logger  # type: ignore[has-type]


@dataclass
class SyncOutcome:
    """Per-market result flags used to build the batch summary."""

    market_changed: bool
    resolution_changed: bool
    category_slug: str | None
    condition_id: str | None
    resolution_cache_payload: dict[str, Any] | None
    market_created: bool = False
    market_updated: bool = False
    group_slugs: set[str] = field(default_factory=set)
    gamma_metadata_updates: int = 0
    timing_match_ms: float = 0.0
    timing_upsert_ms: float = 0.0
    timing_normalized_ms: float = 0.0
    timing_resolution_ms: float = 0.0


@dataclass
class PrefetchedMarketState:
    """Preloaded normalized rows so per-market sync avoids redundant queries."""

    outcomes: dict[int, list[shared_models.MarketOutcome]] = field(default_factory=dict)
    tags: dict[int, set[str]] = field(default_factory=dict)
    clob_tokens: dict[int, list[shared_models.MarketClobToken]] = field(default_factory=dict)
    gamma_metadata: dict[int, shared_models.MarketGammaMetadata] = field(default_factory=dict)


@dataclass
class CleanupOutcome:
    """Retention run result detailing what changed or was eligible for deletion."""

    events: set[str]
    conditions: set[str]
    categories: set[str]
    deleted_rows: int = 0
    eligible_rows: int = 0
    dry_run: bool = False
    category_counts: dict[str, int] | None = None


@dataclass
class SyncSummary:
    """Batch-level change accumulator used for cache invalidation + metrics."""

    changed_events: set[str] = field(default_factory=set)
    changed_conditions: set[str] = field(default_factory=set)
    changed_categories: set[str] = field(default_factory=set)
    changed_group_slugs: set[str] = field(default_factory=set)
    changed_events_total: int = 0
    changed_conditions_total: int = 0
    changed_categories_total: int = 0
    changed_group_slugs_total: int = 0
    resolution_cache_updates: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    proof_jobs: list[tuple[dict[str, Any], MarketPayload, str | None]] = field(default_factory=list)
    stats_dirty: bool = False
    markets_created: int = 0
    markets_updated: int = 0
    markets_deleted: int = 0
    gamma_metadata_updates: int = 0
    proofs_generated: int = 0
    lock_batches_submitted: int = 0
    resolutions_backfilled: int = 0
    failed_markets: int = 0
    cache_invalidations: int = 0
    settlement_txs: int = 0
    polymarket_sync_attempted: bool = False
    timing_match_ms: float = 0.0
    timing_upsert_ms: float = 0.0
    timing_normalized_ms: float = 0.0
    timing_resolution_ms: float = 0.0

    def to_stats(self, markets_processed: int, latency_ms: float, cache_invalidations: int) -> dict[str, Any]:
        return {
            "markets_processed": markets_processed,
            "markets_changed": self.changed_events_total + len(self.changed_events),
            "resolutions_changed": self.changed_conditions_total + len(self.changed_conditions),
            "categories_changed": self.changed_categories_total + len(self.changed_categories),
            "latency_ms": round(latency_ms, 2),
            "markets_created": self.markets_created,
            "markets_updated": self.markets_updated,
            "markets_deleted": self.markets_deleted,
            "proofs_generated": self.proofs_generated,
            "cache_invalidations": cache_invalidations,
            "settlement_txs": self.settlement_txs,
            "lock_batches_submitted": self.lock_batches_submitted,
            "resolutions_backfilled": self.resolutions_backfilled,
            "market_errors": self.failed_markets,
            "gamma_metadata_updates": self.gamma_metadata_updates,
        }


def snapshot_market_record(record) -> dict[str, Any]:
    """Snapshot minimal market identifiers for downstream proof jobs."""
    condition = getattr(record, "condition_id", None)
    return {
        "id": getattr(record, "id", None),
        "event_id": getattr(record, "event_id", None),
        "market_address": getattr(record, "market_address", None),
        "condition_id": condition.lower() if isinstance(condition, str) else condition,
    }


def _slugify_token(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or None


async def _persist_normalized_market_data(
    session: AsyncSession,
    *,
    market_id: int,
    outcomes: list[str] | None,
    outcome_prices: list[float] | None,
    tags: list[str] | None,
    clob_token_ids: list[str] | None,
    gamma_metadata: dict | None,
    prefetched_state: PrefetchedMarketState | None = None,
) -> dict[str, int]:
    """Upsert normalized tables for a market, avoiding unnecessary rewrites."""

    metadata_written = 0
    events_written = 0
    # Outcomes: update only when a payload was provided.
    if outcomes is not None:
        if prefetched_state and market_id in prefetched_state.outcomes:
            existing_outcome_rows = prefetched_state.outcomes.get(market_id, [])
        else:
            existing_outcome_rows = list(
                (
                    await session.execute(
                        select(shared_models.MarketOutcome).where(shared_models.MarketOutcome.market_id == market_id)
                    )
                ).scalars()
            )
        existing_outcomes = {row.outcome_id: row for row in existing_outcome_rows}
        desired: dict[int, tuple[str, Decimal | None]] = {}
        for idx, label in enumerate(outcomes):
            price: Decimal | None = None
            if isinstance(outcome_prices, list) and idx < len(outcome_prices):
                try:
                    price = Decimal(str(outcome_prices[idx]))
                except (TypeError, ValueError, InvalidOperation):
                    price = None
            desired[idx] = (str(label), price)

        # Delete removed outcomes.
        for outcome_id, outcome_row in existing_outcomes.items():
            if outcome_id not in desired:
                await session.delete(outcome_row)
        # Insert/update changed ones.
        for outcome_id, (label_str, price_val) in desired.items():
            existing_outcome = existing_outcomes.get(outcome_id)
            if existing_outcome is None:
                session.add(
                    shared_models.MarketOutcome(
                        market_id=market_id,
                        outcome_id=outcome_id,
                        label=label_str,
                        price=price_val,
                    )
                )
            else:
                existing_price = existing_outcome.price
                if existing_outcome.label != label_str or existing_price != price_val:
                    existing_outcome.label = label_str
                    existing_outcome.price = price_val
                    session.add(existing_outcome)

    # Tags: diff sets when provided.
    if tags is not None:
        if prefetched_state and market_id in prefetched_state.tags:
            existing_tags = prefetched_state.tags.get(market_id, set())
        else:
            existing_tags = {
                row.tag
                for row in (
                    await session.execute(
                        select(shared_models.MarketTag).where(shared_models.MarketTag.market_id == market_id)
                    )
                ).scalars()
            }
        desired_tags = {str(tag).strip() for tag in tags if str(tag).strip()}
        to_delete = existing_tags - desired_tags
        to_insert = desired_tags - existing_tags
        if to_delete:
            await session.execute(
                delete(shared_models.MarketTag).where(
                    shared_models.MarketTag.market_id == market_id,
                    shared_models.MarketTag.tag.in_(to_delete),
                )
            )
        for tag in to_insert:
            session.add(shared_models.MarketTag(market_id=market_id, tag=tag))

    # CLOB tokens: reconcile by token_id.
    if clob_token_ids is not None:
        if prefetched_state and market_id in prefetched_state.clob_tokens:
            existing_clob_rows = prefetched_state.clob_tokens.get(market_id, [])
        else:
            existing_clob_rows = list(
                (
                    await session.execute(
                        select(shared_models.MarketClobToken).where(
                            shared_models.MarketClobToken.market_id == market_id
                        )
                    )
                ).scalars()
            )
        existing_tokens = {row.token_id: row for row in existing_clob_rows}
        desired_tokens: dict[str, str | None] = {}
        for idx, token in enumerate(clob_token_ids):
            side = "yes" if idx == 0 else "no" if idx == 1 else None
            desired_tokens[str(token)] = side
        # Remove missing
        for token_id, token_row in existing_tokens.items():
            if token_id not in desired_tokens:
                await session.delete(token_row)
        # Insert/update
        for token_id, side in desired_tokens.items():
            existing_token = existing_tokens.get(token_id)
            if existing_token is None:
                session.add(shared_models.MarketClobToken(market_id=market_id, token_id=token_id, side=side))
            else:
                if existing_token.side != side:
                    existing_token.side = side
                    session.add(existing_token)

    # Gamma metadata: upsert only when different.
    if gamma_metadata is not None:
        if prefetched_state and market_id in prefetched_state.gamma_metadata:
            existing_meta = prefetched_state.gamma_metadata.get(market_id)
        else:
            existing_meta = (
                await session.execute(
                    select(shared_models.MarketGammaMetadata).where(
                        shared_models.MarketGammaMetadata.market_id == market_id
                    )
                )
            ).scalar_one_or_none()
        if existing_meta is None:
            session.add(shared_models.MarketGammaMetadata(market_id=market_id, **gamma_metadata))
            metadata_written = 1
        else:
            changed = False
            for key, value in gamma_metadata.items():
                if getattr(existing_meta, key, None) != value:
                    setattr(existing_meta, key, value)
                    changed = True
            if changed:
                session.add(existing_meta)
                metadata_written = 1
    # If metadata was not provided, leave existing rows intact to avoid churn.

    # Gamma events no longer persisted.

    return {"metadata": metadata_written, "events": events_written}


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _load_existing_markets(
    session: AsyncSession,
    markets: Sequence[MarketPayload],
) -> dict[str, shared_models.Market]:
    event_ids = [market.event_id for market in markets if isinstance(market.event_id, str)]
    if not event_ids:
        return {}
    existing: dict[str, shared_models.Market] = {}
    chunk_size = 500
    for start in range(0, len(event_ids), chunk_size):
        chunk = event_ids[start : start + chunk_size]
        stmt = select(shared_models.Market).where(shared_models.Market.event_id.in_(chunk))
        result = await session.scalars(stmt)
        for record in result:
            if record.event_id:
                existing[record.event_id] = record
    return existing


async def _prefetch_normalized_state(session: AsyncSession, market_ids: list[int]) -> PrefetchedMarketState:
    """Batch-load normalized rows for the provided market ids."""

    if not market_ids:
        return PrefetchedMarketState()

    outcomes: dict[int, list[shared_models.MarketOutcome]] = {}
    tags: dict[int, set[str]] = {}
    clob_tokens: dict[int, list[shared_models.MarketClobToken]] = {}
    gamma_metadata: dict[int, shared_models.MarketGammaMetadata] = {}

    def _chunk(seq: list[int], size: int = 500):
        for start in range(0, len(seq), size):
            yield seq[start : start + size]

    for chunk in _chunk(market_ids):
        outcome_stmt = select(shared_models.MarketOutcome).where(shared_models.MarketOutcome.market_id.in_(chunk))
        tag_stmt = select(shared_models.MarketTag).where(shared_models.MarketTag.market_id.in_(chunk))
        clob_stmt = select(shared_models.MarketClobToken).where(shared_models.MarketClobToken.market_id.in_(chunk))
        gamma_meta_stmt = select(shared_models.MarketGammaMetadata).where(
            shared_models.MarketGammaMetadata.market_id.in_(chunk)
        )
        for outcome_row in (await session.execute(outcome_stmt)).scalars():
            outcomes.setdefault(outcome_row.market_id, []).append(outcome_row)
        for tag_row in (await session.execute(tag_stmt)).scalars():
            tags.setdefault(tag_row.market_id, set()).add(tag_row.tag)
        for clob_row in (await session.execute(clob_stmt)).scalars():
            clob_tokens.setdefault(clob_row.market_id, []).append(clob_row)
        for gamma_meta_row in (await session.execute(gamma_meta_stmt)).scalars():
            gamma_metadata[gamma_meta_row.market_id] = gamma_meta_row

    return PrefetchedMarketState(
        outcomes=outcomes,
        tags=tags,
        clob_tokens=clob_tokens,
        gamma_metadata=gamma_metadata,
    )


async def collect_market_changes(
    session: AsyncSession, markets: list[MarketPayload], redis_client: Redis | None
) -> SyncSummary:
    """Thin wrapper to collect changes when no existing summary accumulator is provided."""
    return await collect_market_changes_with_summary(session, markets, redis_client, summary=None)


async def collect_market_changes_with_summary(
    session: AsyncSession, markets: list[MarketPayload], redis_client: Redis | None, summary: SyncSummary | None = None
) -> SyncSummary:
    """Upsert a batch of markets and accumulate change flags for cache invalidation + metrics."""
    summary = summary or SyncSummary()
    if not markets:
        return summary
    existing_records = await _load_existing_markets(session, markets)
    existing_ids = [record.id for record in existing_records.values() if record.id is not None]
    commitment_counts: dict[int, int] = {}
    if existing_ids:
        commit_stmt = (
            select(shared_models.Commitment.market_id, func.count(shared_models.Commitment.id))
            .where(shared_models.Commitment.market_id.in_(existing_ids))
            .group_by(shared_models.Commitment.market_id)
        )
        for market_id, count in (await session.execute(commit_stmt)).all():
            commitment_counts[int(market_id)] = int(count or 0)
    prefetch_ids: list[int] = []
    for market in markets:
        existing = existing_records.get(market.event_id)
        market_id = getattr(existing, "id", None) if existing is not None else None
        if market_id is None:
            continue
        incoming_hash = getattr(market, "content_hash", None)
        existing_hash = getattr(existing, "content_hash", None)
        if incoming_hash is None or existing_hash is None or incoming_hash != existing_hash:
            prefetch_ids.append(market_id)
    prefetched_state = await _prefetch_normalized_state(session, sorted(set(prefetch_ids)))
    total_markets = len(markets)
    allow_resolution_fetch: dict[str, bool] = {}
    resolution_summaries: dict[str, dict[str, Any] | None] | None = None
    goldsky = runtime.goldsky_client
    if goldsky is not None:
        now = datetime.now(UTC)
        resolution_requests: list[tuple[str, int | None, list[str] | None]] = []
        for market in markets:
            condition_id = getattr(market, "condition_id", None)
            if not isinstance(condition_id, str) or not condition_id.startswith("0x"):
                allow_resolution_fetch[market.event_id] = False
                continue
            existing = existing_records.get(market.event_id)
            market_id = getattr(existing, "id", None)
            closed_flag = bool(getattr(market, "closed", None) or getattr(existing, "closed", None))
            status_value = getattr(market, "resolution_status", None) or getattr(existing, "resolution_status", None)
            has_commits = bool(market_id and commitment_counts.get(market_id, 0) > 0)
            allow_fetch = closed_flag and status_value == shared_models.ResolutionStatusEnum.FINAL.value and has_commits
            allow_resolution_fetch[market.event_id] = allow_fetch
            if not allow_fetch:
                continue
            closes_at = getattr(market, "closes_at", None) or getattr(existing, "closes_at", None)
            if isinstance(closes_at, datetime) and closes_at.tzinfo is None:
                closes_at = closes_at.replace(tzinfo=UTC)
            if isinstance(closes_at, datetime) and now < closes_at:
                continue
            resolved_at = getattr(existing, "resolved_at", None)
            if status_value == shared_models.ResolutionStatusEnum.FINAL.value and resolved_at is not None:
                continue
            hint = len(market.outcome_prices) if market.outcome_prices else None
            outcomes = market.outcomes if isinstance(market.outcomes, list) else None
            resolution_requests.append((condition_id.lower(), hint, outcomes))
        if resolution_requests:
            try:
                batch_result = await goldsky.resolution_summary_batch(resolution_requests)
                # Normalize keys to lowercase condition ids.
                resolution_summaries = {key.lower(): value for key, value in batch_result.items()}
            except Exception as exc:  # pragma: no cover - best effort; fall back to per-market fetch
                log_event(
                    logger,
                    logging.DEBUG,
                    event="worker.resolution.batch_failed",
                    message="failed to fetch batched goldsky resolutions; falling back to per-market fetch",
                    error=str(exc),
                )
                resolution_summaries = None
    log_event(
        logger,
        logging.DEBUG,
        event="worker.persist.batch",
        message="synchronising markets into database",
        markets_processed=total_markets,
    )
    progress_log_step = max(total_markets // max(runtime.settings.market_progress_log_intervals, 1), 1)
    for index, market in enumerate(markets, start=1):
        if index % progress_log_step == 0 or index == 1 or index == total_markets:
            log_event(
                logger,
                logging.DEBUG,
                event="worker.persist.progress",
                message="market sync progress",
                processed=index,
                total=total_markets,
            )
        try:
            prefetched = existing_records.get(market.event_id)
            db_market, outcome = await sync_market(
                session,
                market,
                existing_market=prefetched,
                prefetched_state=prefetched_state,
                resolution_summaries=resolution_summaries,
                allow_resolution_fetch=allow_resolution_fetch.get(market.event_id, True),
            )
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.WARNING,
                event="worker.persist.market_failed",
                message="failed to synchronise single market",
                event_id=getattr(market, "event_id", None),
                error=str(exc),
                exc_info=exc,
            )
            try:
                await session.rollback()
                session.expunge_all()
            except Exception as rollback_exc:  # pragma: no cover - defensive
                log_event(
                    logger,
                    logging.ERROR,
                    event="worker.persist.rollback_failed",
                    message="failed to rollback after market error; aborting tick",
                    event_id=getattr(market, "event_id", None),
                    error=str(rollback_exc),
                )
                raise
            summary.failed_markets += 1
            # Drop prefetched rows so later iterations do not reuse expired instances after a rollback.
            existing_records = {}
            prefetched_state = PrefetchedMarketState()
            continue
        if db_market and isinstance(db_market.event_id, str):
            existing_records[db_market.event_id] = db_market
        if outcome.market_changed and db_market and db_market.event_id:
            summary.changed_events.add(db_market.event_id)
            summary.stats_dirty = True
        summary.timing_match_ms += outcome.timing_match_ms
        summary.timing_upsert_ms += outcome.timing_upsert_ms
        summary.timing_normalized_ms += outcome.timing_normalized_ms
        summary.timing_resolution_ms += outcome.timing_resolution_ms
        if outcome.market_created:
            summary.markets_created += 1
        if outcome.market_updated:
            summary.markets_updated += 1
        if outcome.resolution_changed and outcome.condition_id:
            summary.changed_conditions.add(outcome.condition_id.lower())
        if outcome.category_slug and (outcome.market_changed or outcome.market_created or outcome.market_updated):
            summary.changed_categories.add(outcome.category_slug)
        if outcome.group_slugs:
            summary.changed_group_slugs.update(outcome.group_slugs)
        if outcome.resolution_cache_payload and outcome.condition_id:
            summary.resolution_cache_updates.append((outcome.condition_id, outcome.resolution_cache_payload))
        if outcome.gamma_metadata_updates:
            summary.gamma_metadata_updates += outcome.gamma_metadata_updates
            summary.stats_dirty = True
        if runtime.PROVER_CLIENT is not None and db_market is not None and db_market.id is not None:
            if getattr(db_market, "resolution_status", None) not in (
                None,
                shared_models.ResolutionStatusEnum.FINAL.value,
            ):
                log_event(
                    logger,
                    logging.INFO,
                    event="worker.proof.skipped_resolution_pending",
                    message="skipping proof job because resolution not final",
                    event_id=db_market.event_id,
                    resolution_status=getattr(db_market, "resolution_status", None),
                )
                continue
            # Only proceed if the market had Reveal activity (commitments exist).
            commitment_count = 0
            if db_market.id is not None:
                commitment_count = commitment_counts.get(int(db_market.id), 0)
            if commitment_count <= 0:
                continue
            if not getattr(db_market, "market_address", None):
                log_event(
                    logger,
                    logging.INFO,
                    event="worker.proof.skipped_missing_address",
                    message="skipping proof job because market address is missing",
                    event_id=db_market.event_id,
                    market_id=db_market.id,
                )
                continue
            settlement = await session.scalar(
                select(shared_models.Settlement).where(shared_models.Settlement.market_id == db_market.id)
            )
            if settlement is None or settlement_needs_refresh(settlement):
                # Best-effort hydrate settlement from chain once when we have a final resolution and commitments.
                hydrated = None
                try:
                    if getattr(db_market, "market_address", None):
                        hydrated = await _upsert_settlement_from_chain(session, db_market)
                        if hydrated is not None:
                            settlement = hydrated
                        else:
                            # Refresh local view if a new row was inserted.
                            settlement = await session.scalar(
                                select(shared_models.Settlement).where(
                                    shared_models.Settlement.market_id == db_market.id
                                )
                            )
                except Exception as exc:
                    log_event(
                        logger,
                        logging.INFO,
                        event="worker.proof.hydrate_failed",
                        message="failed to hydrate settlement from chain",
                        event_id=db_market.event_id,
                        market_id=db_market.id,
                        market_address=getattr(db_market, "market_address", None),
                        error=str(exc),
                    )
                if settlement is None or settlement_needs_refresh(settlement):
                    missing_parts = []
                    if settlement is None:
                        missing_parts.append("no_settlement")
                    else:
                        batch_roots = getattr(settlement, "batch_roots", None)
                        merkle_root = getattr(settlement, "merkle_root", None)
                        if not batch_roots and not merkle_root:
                            missing_parts.append("roots")
                        if settlement.winning_outcome_id is None:
                            missing_parts.append("winner")
                        if not getattr(settlement, "circuit_hash", None):
                            missing_parts.append("circuit_hash")
                        if settlement.total_escrow is None or settlement.total_liability is None:
                            missing_parts.append("totals")
                    log_event(
                        logger,
                        logging.INFO,
                        event="worker.proof.skipped_missing_settlement",
                        message="skipping proof job because settlement snapshot is missing or incomplete",
                        event_id=db_market.event_id,
                        market_id=db_market.id,
                        market_address=getattr(db_market, "market_address", None),
                        has_commitments=bool(commitment_count),
                        missing=",".join(missing_parts) if missing_parts else None,
                    )
                    continue
            if settlement.proof_status == shared_models.SettlementProofStatus.GENERATED.value:
                log_event(
                    logger,
                    logging.INFO,
                    event="worker.proof.skipped_existing",
                    message="skipping proof job because proof already generated",
                    event_id=db_market.event_id,
                    market_id=db_market.id,
                )
            else:
                summary.proof_jobs.append(
                    (
                        snapshot_market_record(db_market),
                        market,
                        outcome.condition_id,
                    )
                )
    return summary


def market_record_to_payload(record: shared_models.Market) -> MarketPayload:
    """Convert an ORM Market row into a MarketPayload (used for backfills/tests)."""
    try:
        outcome_rows = list(record.outcomes_rel)
    except Exception:
        outcome_rows = None
    outcomes = [row.label for row in outcome_rows] if outcome_rows is not None else None
    prices_raw: list[float | None] | None = None
    if outcome_rows is not None:
        prices_raw = []
        any_price = False
        for row in outcome_rows:
            prices_raw.append(float(row.price) if row.price is not None else None)
            any_price = any_price or row.price is not None
        if not any_price:
            prices_raw = None
    prices: list[float] | None = None
    if prices_raw is not None:
        prices = [price for price in prices_raw if price is not None]
    try:
        tags = [row.tag for row in record.tags_rel]
    except Exception:
        tags = None
    try:
        clob_ids = [row.token_id for row in record.clob_tokens_rel]
    except Exception:
        clob_ids = None
    try:
        gamma_meta = record.gamma_metadata_rel
    except Exception:
        gamma_meta = None
    group_slug = getattr(record, "group_slug", None) or (
        getattr(gamma_meta, "group_slug", None) if gamma_meta else None
    )
    event_key = getattr(record, "event_key", None)
    group_position = getattr(record, "group_position", None)
    group_item_title = getattr(gamma_meta, "group_item_title", None) if gamma_meta else None
    group_item_threshold = (
        _parse_group_threshold(getattr(gamma_meta, "group_item_threshold", None)) if gamma_meta else None
    )
    if group_position is None and group_item_threshold is not None:
        try:
            group_position = int(group_item_threshold)
        except (TypeError, ValueError, OverflowError):
            group_position = None

    image_variants: list[str] | None = None
    if isinstance(record.image_variants, dict):
        image_variants = [str(value) for value in record.image_variants.values() if value is not None]
    elif isinstance(record.image_variants, list):
        image_variants = [str(value) for value in record.image_variants if value is not None]

    return MarketPayload(
        event_id=record.event_id,
        title=record.title or record.event_id or "Market",
        slug=record.slug,
        category=record.category,
        metadata_uri=record.metadata_uri,
        oracle=record.oracle or "polymarket",
        factory=record.factory,
        market_address=record.market_address,
        status=record.status or shared_models.MarketStatusEnum.COMMIT.value,
        outcomes=outcomes,
        outcome_prices=prices,
        tags=tags,
        clob_token_ids=clob_ids,
        gamma_metadata={k: v for k, v in vars(gamma_meta).items() if not k.startswith("_")} if gamma_meta else None,
        rake_bps=record.rake_bps,
        condition_id=record.condition_id,
        question_id=record.question_id,
        image_url=record.image_url,
        closed=record.closed,
        uma_resolution_status=record.uma_resolution_status,
        source_updated_at=record.source_updated_at,
        content_hash=record.content_hash,
        starts_at=record.starts_at,
        orders_opened_at=record.orders_opened_at,
        resolution_source=record.resolution_source,
        resolution_status=getattr(record, "resolution_status", None),
        resolution_reason=getattr(record, "resolution_reason", None),
        commits_blocked_at=getattr(record, "commits_blocked_at", None),
        market_maker=record.market_maker,
        order_min_size=float(record.order_min_size) if record.order_min_size is not None else None,
        price_tick_size=float(record.price_tick_size) if record.price_tick_size is not None else None,
        enable_order_book=record.enable_order_book,
        image_variants=image_variants,
        closes_at=record.closes_at,
        group_slug=group_slug,
        event_key=event_key,
        group_position=group_position,
        group_item_title=group_item_title,
        group_item_threshold=group_item_threshold,
    )


async def sync_market(
    session: AsyncSession,
    market: MarketPayload,
    existing_market: shared_models.Market | None = None,
    prefetched_state: PrefetchedMarketState | None = None,
    resolution_summaries: dict[str, dict[str, Any] | None] | None = None,
    allow_resolution_fetch: bool = True,
):
    """Upsert a market row using `event_id` as the natural key, reusing prefetched state when available."""
    if market.event_key:
        market.group_slug = market.event_key
    return await _sync_market(
        session,
        market,
        existing_market=existing_market,
        prefetched_state=prefetched_state,
        resolution_summaries=resolution_summaries,
        allow_resolution_fetch=allow_resolution_fetch,
    )


async def _record_factory_state(
    session: AsyncSession, market: shared_models.Market | None, payload: MarketPayload
) -> None:
    """Mirror factory/rake events into the ledger so address drift is auditable."""

    factory_address = payload.factory or getattr(market, "factory", None) or runtime.settings.factory_address
    if not factory_address:
        return
    market_address = payload.market_address or getattr(market, "market_address", None)
    event_payload = {
        "rake_bps": payload.rake_bps if hasattr(payload, "rake_bps") else None,
        "oracle": payload.oracle,
        "event_id": payload.event_id,
    }
    await shared_repository.record_factory_event(
        session,
        factory_address=str(factory_address),
        market_address=str(market_address) if market_address else None,
        event="sync",
        tx_hash=None,
        block_number=None,
        block_timestamp=None,
        payload=event_payload,
    )


def _factory_event_changed(
    previous: dict[str, Any] | None,
    current: shared_models.Market | None,
) -> bool:
    if current is None:
        return False
    if previous is None:
        return True
    for key in ("factory", "market_address", "oracle", "rake_bps"):
        if previous.get(key) != getattr(current, key, None):
            return True
    return False


def _markets_match(
    existing,
    source_updated_at: datetime | None,
    content_hash: str | None,
    resolution_status: str | None = None,
    resolution_reason: str | None = None,
    commits_blocked_at: datetime | None = None,
    *,
    resolution_status_provided: bool = False,
    resolution_reason_provided: bool = False,
    commits_blocked_at_provided: bool = False,
) -> tuple[bool, str]:
    """Check whether incoming payload matches the existing record to skip writes."""
    if resolution_status_provided and getattr(existing, "resolution_status", None) != resolution_status:
        return False, "resolution_status_changed"
    if resolution_reason_provided and getattr(existing, "resolution_reason", None) != resolution_reason:
        return False, "resolution_reason_changed"
    if commits_blocked_at_provided and getattr(existing, "commits_blocked_at", None) != commits_blocked_at:
        return False, "commits_blocked_at_changed"
    existing_source_ts = _as_utc(getattr(existing, "source_updated_at", None))
    incoming_source_ts = _as_utc(source_updated_at)
    existing_hash = getattr(existing, "content_hash", None)
    if content_hash is not None:
        if existing_hash != content_hash:
            return False, "content_hash_changed"
        if content_hash:
            return True, "content_hash"
    if incoming_source_ts and existing_source_ts and existing_source_ts == incoming_source_ts:
        return True, "source_timestamp"
    return False, "diff_detected"


def _should_close_market(close_deadline: datetime | None, explicit_closed: bool | None, now: datetime) -> bool:
    return bool(explicit_closed)


def _build_cleanup_outcome(records, cutoff: datetime, dry_run: bool) -> CleanupOutcome:
    if not records:
        return CleanupOutcome(
            set(),
            set(),
            set(),
            deleted_rows=0,
            eligible_rows=0,
            dry_run=dry_run,
            category_counts={},
        )

    event_ids: set[str] = set()
    condition_ids: set[str] = set()
    categories: set[str] = set()
    category_counts: dict[str, int] = {}
    ids_to_delete: list[int] = []

    for row in records:
        resolved_at = _as_utc(row.resolved_at)
        closes_at = _as_utc(getattr(row, "closes_at", None))
        is_closed = bool(getattr(row, "closed", False))
        resolved_expired = resolved_at is not None and resolved_at <= cutoff
        closed_expired = is_closed and closes_at is not None and closes_at <= cutoff
        if not resolved_expired and not closed_expired:
            continue
        if row.id is not None:
            ids_to_delete.append(row.id)
        if row.event_id:
            event_ids.add(row.event_id)
        if isinstance(row.condition_id, str):
            condition_ids.add(row.condition_id.lower())
        cat_slug = _slugify_token(row.category)
        if cat_slug:
            categories.add(cat_slug)
        normalized_category = cat_slug or "uncategorized"
        category_counts[normalized_category] = category_counts.get(normalized_category, 0) + 1

    eligible = len(ids_to_delete)
    if eligible == 0:
        return CleanupOutcome(
            event_ids,
            condition_ids,
            categories,
            deleted_rows=0,
            eligible_rows=0,
            dry_run=dry_run,
            category_counts=category_counts,
        )

    record_retention_metrics(category_counts)
    log_event(
        logger,
        logging.DEBUG,
        event="worker.retention.cleanup",
        message="evaluated resolved markets for retention (historical retention disabled)",
        eligible=eligible,
        deleted=0,
        dry_run=True,
        cutoff=cutoff.isoformat(),
    )
    return CleanupOutcome(
        event_ids,
        condition_ids,
        categories,
        deleted_rows=0,
        eligible_rows=eligible,
        dry_run=True,
        category_counts=category_counts,
    )


async def _sync_market(
    session: AsyncSession,
    market: MarketPayload,
    existing_market: shared_models.Market | None = None,
    prefetched_state: PrefetchedMarketState | None = None,
    resolution_summaries: dict[str, dict[str, Any] | None] | None = None,
    allow_resolution_fetch: bool = True,
):
    """Async implementation that upserts market state + resolutions."""
    now = datetime.now(UTC)
    existing = existing_market or await shared_repository.get_market_by_event_id(session, market.event_id)
    if existing is not None:
        state: InstanceState[shared_models.Market] | None = inspect(existing)
        if state is not None and state.detached:
            existing = await shared_repository.get_market_by_event_id(session, market.event_id)
            state = inspect(existing) if existing is not None else None
    if existing is not None and state is not None and state.expired_attributes:
        await session.refresh(existing)
    previous_group_slug = getattr(existing, "group_slug", None) if existing is not None else None
    factory_snapshot: dict[str, Any] | None = None
    if existing is not None:
        factory_snapshot = {
            "factory": getattr(existing, "factory", None),
            "market_address": getattr(existing, "market_address", None),
            "oracle": getattr(existing, "oracle", None),
            "rake_bps": getattr(existing, "rake_bps", None),
        }
    payload = market.model_dump()
    if payload.get("closed") is None:
        payload["closed"] = False
    condition_id = payload.get("condition_id")
    if isinstance(condition_id, str):
        payload["condition_id"] = condition_id.lower()
    close_deadline = payload.get("closes_at")
    if close_deadline is None and existing is not None:
        close_deadline = getattr(existing, "closes_at", None)
        if close_deadline is not None:
            payload["closes_at"] = close_deadline
    deadline = close_deadline
    if isinstance(deadline, datetime) and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    deadline_passed = bool(deadline and deadline <= now)
    should_close = _should_close_market(deadline, market.closed, now)
    payload["closed"] = should_close
    existing_resolution_status = getattr(existing, "resolution_status", None)
    incoming_resolution_status = payload.get("resolution_status")
    incoming_resolution_reason = payload.get("resolution_reason")
    resolution_provided = incoming_resolution_status is not None or incoming_resolution_reason is not None
    resolution_status = incoming_resolution_status if resolution_provided else existing_resolution_status
    resolution_reason = incoming_resolution_reason or getattr(existing, "resolution_reason", None)
    existing_blocked_at = getattr(existing, "commits_blocked_at", None)
    blocked_at = payload.get("commits_blocked_at") or existing_blocked_at
    resolution_status_changed = (
        incoming_resolution_status is not None and incoming_resolution_status != existing_resolution_status
    )
    payload["resolution_status"] = resolution_status
    if resolution_reason:
        payload["resolution_reason"] = resolution_reason
    else:
        payload.pop("resolution_reason", None)
    commit_block_lead = max(300, int(getattr(runtime.settings, "commit_cutoff_seconds", 0) or 0))
    cutoff_deadline = deadline
    if cutoff_deadline and not cutoff_deadline.tzinfo:
        cutoff_deadline = cutoff_deadline.replace(tzinfo=UTC)
    cutoff_time = cutoff_deadline - timedelta(seconds=commit_block_lead) if cutoff_deadline else None
    if cutoff_time and now >= cutoff_time:
        blocked_at = cutoff_time
    elif blocked_at is None and (should_close or deadline_passed):
        blocked_at = cutoff_time or now
    if resolution_status_changed and incoming_resolution_status in {
        shared_models.ResolutionStatusEnum.PENDING.value,
        shared_models.ResolutionStatusEnum.DISPUTED.value,
    }:
        should_close = True
        payload["closed"] = True
        if blocked_at is None:
            blocked_at = now
    payload["commits_blocked_at"] = blocked_at
    status_value = payload.get("status") or shared_models.MarketStatusEnum.COMMIT.value
    if (should_close or deadline_passed or (cutoff_time and now >= cutoff_time)) and status_value not in {
        shared_models.MarketStatusEnum.SETTLED.value,
        shared_models.MarketStatusEnum.CANCELLED.value,
    }:
        status_value = shared_models.MarketStatusEnum.LOCKED.value
    payload["status"] = status_value

    market.closed = payload["closed"]
    market.status = status_value
    market.commits_blocked_at = blocked_at
    market.resolution_status = resolution_status
    market.resolution_reason = payload.get("resolution_reason")
    market.content_hash = _compute_market_hash(_build_market_hash_payload(market))
    payload["content_hash"] = market.content_hash

    if logger.isEnabledFor(logging.DEBUG):
        log_event(
            logger,
            logging.DEBUG,
            event="worker.market.payload_ready",
            message="prepared market payload for persistence",
            event_id=market.event_id,
            existing=existing is not None,
            should_close=should_close,
            status=status_value,
        )

    db_market = existing
    market_changed = False
    market_created = False
    market_updated = False
    incoming_updated_at = getattr(market, "source_updated_at", None)
    incoming_hash = payload.get("content_hash")
    timing_match_ms = 0.0
    timing_upsert_ms = 0.0
    timing_normalized_ms = 0.0
    timing_resolution_ms = 0.0

    outcomes = payload.pop("outcomes", None)
    outcome_prices = payload.pop("outcome_prices", None)
    tags = payload.pop("tags", None)
    clob_token_ids = payload.pop("clob_token_ids", None)
    gamma_metadata = payload.pop("gamma_metadata", None)
    gamma_counts = {"metadata": 0, "events": 0}

    # Assign public_event_id: all markets in the same group share one 8-char hex ID.
    if not payload.get("public_event_id") and not getattr(existing, "public_event_id", None):
        group_key = payload.get("group_slug") or payload.get("event_key") or payload.get("event_id")
        sibling_id: str | None = None
        if group_key:
            row = (
                await session.execute(
                    select(shared_models.Market.public_event_id)
                    .where(
                        or_(
                            shared_models.Market.group_slug == group_key,
                            shared_models.Market.event_key == group_key,
                        ),
                        shared_models.Market.public_event_id.isnot(None),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            sibling_id = row
        payload["public_event_id"] = sibling_id or uuid.uuid4().hex[:8]

    if existing is None:
        upsert_start = time.perf_counter()
        db_market = await shared_repository.upsert_market(session, payload, existing)
        timing_upsert_ms = (time.perf_counter() - upsert_start) * 1000
        market_changed = True
        market_created = True
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                event="worker.market.created",
                message="market created from polymarket feed",
                event_id=market.event_id,
                status=payload.get("status"),
                category=payload.get("category"),
            )
    else:
        match_start = time.perf_counter()
        match, match_reason = _markets_match(
            existing,
            incoming_updated_at,
            incoming_hash,
            resolution_status=resolution_status,
            resolution_reason=resolution_reason,
            commits_blocked_at=blocked_at,
            resolution_status_provided=resolution_provided,
            resolution_reason_provided=resolution_provided and resolution_reason is not None,
            commits_blocked_at_provided=blocked_at is not None,
        )
        timing_match_ms = (time.perf_counter() - match_start) * 1000
        if match:
            if logger.isEnabledFor(logging.DEBUG):
                log_event(
                    logger,
                    logging.DEBUG,
                    event="worker.market.skip_update",
                    message="skipping market update (no changes detected)",
                    event_id=market.event_id,
                    reason=match_reason,
                )
            category_slug = _slugify_token(getattr(existing, "category", None))
            condition_value = getattr(existing, "condition_id", None)
            condition_normalized = condition_value.lower() if isinstance(condition_value, str) else condition_value
            group_slugs = set()
            for slug in (previous_group_slug, getattr(existing, "group_slug", None)):
                if isinstance(slug, str) and slug:
                    group_slugs.add(slug)
            return existing, SyncOutcome(
                market_changed=False,
                resolution_changed=False,
                category_slug=category_slug,
                condition_id=condition_normalized,
                resolution_cache_payload=None,
                market_created=False,
                market_updated=False,
                group_slugs=group_slugs,
                gamma_metadata_updates=0,
                timing_match_ms=timing_match_ms,
                timing_upsert_ms=timing_upsert_ms,
                timing_normalized_ms=timing_normalized_ms,
                timing_resolution_ms=timing_resolution_ms,
            )
        else:
            upsert_start = time.perf_counter()
            db_market = await shared_repository.upsert_market(session, payload, existing)
            timing_upsert_ms = (time.perf_counter() - upsert_start) * 1000
            market_changed = True
            market_updated = True
            if logger.isEnabledFor(logging.DEBUG):
                log_event(
                    logger,
                    logging.DEBUG,
                    event="worker.market.updated",
                    message="market updated from polymarket feed",
                    event_id=market.event_id,
                    status=payload.get("status"),
                    category=payload.get("category"),
                    match_reason=match_reason,
                )

    if market.rake_bps is not None and db_market is not None:
        db_market.rake_bps = market.rake_bps

    if db_market is not None:
        if db_market.id is None:
            await session.flush()
        norm_start = time.perf_counter()
        gamma_counts = await _persist_normalized_market_data(
            session,
            market_id=db_market.id,
            outcomes=outcomes,
            outcome_prices=outcome_prices,
            tags=tags,
            clob_token_ids=clob_token_ids,
            gamma_metadata=gamma_metadata,
            prefetched_state=prefetched_state,
        )
        timing_normalized_ms = (time.perf_counter() - norm_start) * 1000
        if gamma_counts.get("metadata") or gamma_counts.get("events"):
            log_event(
                logger,
                logging.DEBUG,
                event="worker.market.gamma_updated",
                message="updated gamma metadata/events",
                event_id=market.event_id,
                metadata=gamma_counts.get("metadata", 0),
                events=gamma_counts.get("events", 0),
            )
    else:
        gamma_counts = {"metadata": 0, "events": 0}
    if _factory_event_changed(factory_snapshot, db_market):
        await _record_factory_state(session, db_market, market)
    if db_market is not None:
        # Clear stale relationship collections to avoid reusing deleted instances without triggering lazy loads.
        relationship_resets: dict[str, list[Any] | None] = {
            "outcomes_rel": [],
            "tags_rel": [],
            "clob_tokens_rel": [],
            "gamma_metadata_rel": None,
        }
        for rel_key, value in relationship_resets.items():
            try:
                set_committed_value(db_market, rel_key, value)
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    log_event(
                        logger,
                        logging.DEBUG,
                        event="worker.market.relationship_clear_failed",
                        message="failed to clear relationship cache",
                        market_id=getattr(db_market, "event_id", None),
                        relationship=rel_key,
                    )
    resolution_start = time.perf_counter()
    resolution_outcome = await apply_resolution(
        session,
        db_market,
        market,
        summary_overrides=resolution_summaries,
        allow_resolution_fetch=allow_resolution_fetch,
    )
    timing_resolution_ms = (time.perf_counter() - resolution_start) * 1000
    await session.flush()
    category_slug = _slugify_token(getattr(db_market, "category", None))
    current_group_slug = getattr(db_market, "group_slug", None)
    group_slugs = set()
    for slug in (previous_group_slug, current_group_slug):
        if isinstance(slug, str) and slug:
            group_slugs.add(slug)
    return db_market, SyncOutcome(
        market_changed=market_changed,
        resolution_changed=resolution_outcome.changed,
        category_slug=category_slug,
        condition_id=resolution_outcome.condition_id,
        resolution_cache_payload=resolution_outcome.cache_payload,
        market_created=market_created,
        market_updated=market_updated,
        group_slugs=group_slugs,
        gamma_metadata_updates=gamma_counts.get("metadata", 0),
        timing_match_ms=timing_match_ms,
        timing_upsert_ms=timing_upsert_ms,
        timing_normalized_ms=timing_normalized_ms,
        timing_resolution_ms=timing_resolution_ms,
    )


def _cleanup_resolved_stmt(now: datetime | None = None):
    """Build the query statement and cutoff for cleanup_resolved_markets."""
    reference_time = _as_utc(now) or datetime.now(UTC)
    cutoff = reference_time - timedelta(seconds=runtime.settings.resolved_retention_seconds)
    stmt = select(
        shared_models.Market.id,
        shared_models.Market.event_id,
        shared_models.Market.condition_id,
        shared_models.Market.category,
        shared_models.Market.resolved_at,
        shared_models.Market.closes_at,
        shared_models.Market.closed,
    ).where(
        or_(
            shared_models.Market.resolved_at.isnot(None) & (shared_models.Market.resolved_at < cutoff),
            shared_models.Market.closed.is_(True)
            & shared_models.Market.closes_at.isnot(None)
            & (shared_models.Market.closes_at < cutoff),
        )
    )
    return stmt, cutoff


def cleanup_resolved_markets(  # noqa: C901
    session: Session,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> CleanupOutcome:
    """Remove markets that have been resolved for longer than the configured retention."""
    stmt, cutoff = _cleanup_resolved_stmt(now)
    records = session.execute(stmt).all()
    return _build_cleanup_outcome(records, cutoff, dry_run)


async def cleanup_resolved_markets_async(  # noqa: C901
    session: AsyncSession,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> CleanupOutcome:
    """Remove markets that have been resolved for longer than the configured retention."""
    stmt, cutoff = _cleanup_resolved_stmt(now)
    records = (await session.execute(stmt)).all()
    return _build_cleanup_outcome(records, cutoff, dry_run)


async def _backfill_missing_resolutions(session: AsyncSession, summary: SyncSummary) -> int:
    """Hydrate historical resolutions for markets missing ledger entries."""

    limit = max(0, getattr(runtime.settings, "resolution_backfill_limit", 0))
    if limit <= 0:
        return 0

    stmt = (
        select(shared_models.Market)
        .where(
            shared_models.Market.condition_id.isnot(None),
            ~shared_models.Market.condition_id.in_(select(shared_models.Resolution.condition_id)),
        )
        .limit(limit)
    )
    backfilled = 0
    records = (await session.scalars(stmt)).all()
    for record in records:
        if not record.condition_id or not record.event_id:
            continue
        try:
            payload = market_record_to_payload(record)
        except (TypeError, ValueError, KeyError) as exc:  # pragma: no cover - defensive guard
            log_event(
                logger,
                logging.WARNING,
                event="worker.resolution.backfill_payload_failed",
                message="failed to convert market record to payload for backfill",
                event_id=getattr(record, "event_id", None),
                error=str(exc),
            )
            continue
        outcome = await apply_resolution(session, record, payload)
        if outcome.changed and outcome.condition_id:
            summary.changed_conditions.add(outcome.condition_id)
            if outcome.cache_payload:
                summary.resolution_cache_updates.append((outcome.condition_id, outcome.cache_payload))
            backfilled += 1
    summary.resolutions_backfilled += backfilled
    return backfilled


async def backfill_missing_resolutions_async(session: AsyncSession, summary: SyncSummary) -> int:
    return await _backfill_missing_resolutions(session, summary)


def _count_resolution_gaps(session: Session) -> tuple[int, list[str]]:
    cutoff_seconds = getattr(runtime.settings, "resolution_gap_warn_seconds", 0)
    if cutoff_seconds <= 0:
        return 0, []
    cutoff = datetime.now(UTC) - timedelta(seconds=cutoff_seconds)
    stmt = select(
        shared_models.Market.event_id,
        shared_models.Market.condition_id,
        shared_models.Market.resolved_at,
    ).where(
        shared_models.Market.condition_id.isnot(None),
        shared_models.Market.resolved_at.isnot(None),
        shared_models.Market.resolved_at < cutoff,
        ~shared_models.Market.condition_id.in_(select(shared_models.Resolution.condition_id)),
    )
    events: list[str] = []
    for event_id, _condition_id, _resolved_at in session.execute(stmt):
        if isinstance(event_id, str):
            events.append(event_id)
    return len(events), events


async def _count_resolution_gaps_async(session: AsyncSession) -> tuple[int, list[str]]:
    cutoff_seconds = getattr(runtime.settings, "resolution_gap_warn_seconds", 0)
    if cutoff_seconds <= 0:
        return 0, []
    cutoff = datetime.now(UTC) - timedelta(seconds=cutoff_seconds)
    stmt = select(
        shared_models.Market.event_id,
        shared_models.Market.condition_id,
        shared_models.Market.resolved_at,
    ).where(
        shared_models.Market.condition_id.isnot(None),
        shared_models.Market.resolved_at.isnot(None),
        shared_models.Market.resolved_at < cutoff,
        ~shared_models.Market.condition_id.in_(select(shared_models.Resolution.condition_id)),
    )
    events: list[str] = []
    result = await session.execute(stmt)
    for event_id, _condition_id, _resolved_at in result:
        if isinstance(event_id, str):
            events.append(event_id)
    return len(events), events


def _log_resolution_gaps(session: Session) -> int:
    threshold = getattr(runtime.settings, "resolution_gap_warn_threshold", 0)
    if threshold <= 0:
        return 0
    count, events = _count_resolution_gaps(session)
    if count >= threshold:
        log_event(
            logger,
            logging.WARNING,
            event="worker.resolution.gaps",
            message="markets missing resolution ledger entries",
            gaps=count,
            sample_events=events[: min(len(events), 5)],
        )
    return count


async def log_resolution_gaps_async(session: AsyncSession) -> int:
    threshold = getattr(runtime.settings, "resolution_gap_warn_threshold", 0)
    if threshold <= 0:
        return 0
    count, events = await _count_resolution_gaps_async(session)
    if count >= threshold:
        log_event(
            logger,
            logging.WARNING,
            event="worker.resolution.gaps",
            message="markets missing resolution ledger entries",
            gaps=count,
            sample_events=events[: min(len(events), 5)],
        )
    return count


def apply_retention_cleanup(session: Session, summary: SyncSummary) -> None:
    cleanup_outcome = cleanup_resolved_markets(session, dry_run=runtime.settings.resolved_retention_dry_run)
    if cleanup_outcome.events:
        summary.changed_events.update(cleanup_outcome.events)
        summary.stats_dirty = True
    summary.changed_conditions.update(cleanup_outcome.conditions)
    summary.changed_categories.update(cleanup_outcome.categories)
    summary.markets_deleted = cleanup_outcome.deleted_rows
    if cleanup_outcome.category_counts:
        record_retention_metrics(cleanup_outcome.category_counts)


async def apply_retention_cleanup_async(session: AsyncSession, summary: SyncSummary) -> None:
    cleanup_outcome = await cleanup_resolved_markets_async(session, dry_run=runtime.settings.resolved_retention_dry_run)
    if cleanup_outcome.events:
        summary.changed_events.update(cleanup_outcome.events)
        summary.stats_dirty = True
    summary.changed_conditions.update(cleanup_outcome.conditions)
    summary.changed_categories.update(cleanup_outcome.categories)
    summary.markets_deleted = cleanup_outcome.deleted_rows
    if cleanup_outcome.category_counts:
        record_retention_metrics(cleanup_outcome.category_counts)
