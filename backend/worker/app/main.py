"""Worker public API surface: re-export core helpers and provide CLI entrypoint."""

from __future__ import annotations

import asyncio
from typing import Any

from . import runtime
from .cache_ops import invalidate_cache_tags, persist_resolution_cache_updates
from .market_sync import (
    CleanupOutcome,
    SyncOutcome,
    SyncSummary,
    cleanup_resolved_markets,
    collect_market_changes,
    collect_market_changes_with_summary,
)
from .metrics import (
    CACHE_INVALIDATION_COUNTER,
    POLYMARKET_EMPTY_PAGE_COUNTER,
    POLYMARKET_FETCH_COUNTER,
    POLYMARKET_RATE_LIMIT_COUNTER,
    POLYMARKET_RETRY_COUNTER,
    RETENTION_METRIC,
    CacheInvalidationReport,
)
from .polymarket import build_filters_from_settings
from .prime import prime_featured_views, prime_markets_cache
from .proofs import maybe_generate_settlement_proof
from .resolution import ResolutionOutcome, _fetch_resolution_snapshot, apply_resolution
from .runtime import (
    PROVER_CLIENT,
    clob_client,
    goldsky_client,
    logger,
    polymarket_client,
    settings,
)
from .schema import SchemaSyncResult
from .service import process_once, publish_heartbeat, record_batch_stats, run_worker
from .settlement import run_settlement_jobs


def main() -> None:  # pragma: no cover - CLI bootstrap
    """CLI entrypoint used by Docker/Procfile executions."""
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:  # pragma: no cover - graceful shutdown
        logger.info("worker interrupted, shutting down")
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("worker crashed", extra={"event": "worker.crash", "error": str(exc)})


def __getattr__(name: str) -> Any:
    """Expose runtime-held singletons (settings/clients) for legacy imports."""
    dynamic_attrs = {
        "settings",
        "polymarket_client",
        "clob_client",
        "goldsky_client",
        "PROVER_CLIENT",
    }
    if name in dynamic_attrs:
        return getattr(runtime, name.lower() if name.islower() else name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "apply_resolution",
    "build_filters_from_settings",
    "cleanup_resolved_markets",
    "collect_market_changes",
    "collect_market_changes_with_summary",
    "invalidate_cache_tags",
    "persist_resolution_cache_updates",
    "run_settlement_jobs",
    "prime_featured_views",
    "prime_markets_cache",
    "process_once",
    "publish_heartbeat",
    "record_batch_stats",
    "run_worker",
    "maybe_generate_settlement_proof",
    "_fetch_resolution_snapshot",
    "SchemaSyncResult",
    "SyncOutcome",
    "SyncSummary",
    "CleanupOutcome",
    "ResolutionOutcome",
    "CacheInvalidationReport",
    "CACHE_INVALIDATION_COUNTER",
    "POLYMARKET_EMPTY_PAGE_COUNTER",
    "POLYMARKET_FETCH_COUNTER",
    "POLYMARKET_RATE_LIMIT_COUNTER",
    "POLYMARKET_RETRY_COUNTER",
    "RETENTION_METRIC",
    "PROVER_CLIENT",
    "clob_client",
    "goldsky_client",
    "polymarket_client",
    "settings",
    "logger",
]
