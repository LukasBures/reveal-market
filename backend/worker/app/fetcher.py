"""Polymarket ingestion helpers: fetch markets and enrich with CLOB data."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
from shared.logging import log_event

from . import runtime
from .metrics import POLYMARKET_FETCH_COUNTER
from .polymarket import MarketPayload, merge_clob_markets


def build_filters_from_settings(settings_obj=None) -> dict[str, Any]:
    """Translate worker settings into Gamma API query params."""
    settings_obj = settings_obj or runtime.settings
    params: dict[str, Any] = {}
    if settings_obj.polymarket_active_filter is not None:
        params["active"] = str(settings_obj.polymarket_active_filter).lower()
    if settings_obj.polymarket_archived_filter is not None:
        params["archived"] = str(settings_obj.polymarket_archived_filter).lower()
    return params


async def fetch_markets_from_polymarket() -> tuple[list[MarketPayload], float]:
    """Pull the latest markets from Polymarket using the shared client."""
    start = time.perf_counter()
    log_event(
        runtime.logger,
        logging.DEBUG,
        event="worker.fetch.start",
        message="fetching markets from polymarket",
        page_size=runtime.settings.polymarket_page_size,
        max_pages=runtime.settings.polymarket_max_pages,
        order=runtime.settings.polymarket_order,
        ascending=runtime.settings.polymarket_sort_ascending,
        closed=runtime.settings.polymarket_closed_filter,
        active=runtime.settings.polymarket_active_filter,
        archived=runtime.settings.polymarket_archived_filter,
    )

    max_attempts = max(1, runtime.settings.polymarket_sync_max_attempts)
    base_backoff = max(runtime.settings.polymarket_sync_retry_backoff_seconds, 0.0)
    backoff_max = max(runtime.settings.polymarket_sync_retry_backoff_max_seconds, 0.0)
    attempt = 0
    while True:
        attempt += 1
        try:
            markets = await runtime.polymarket_client.fetch_events_markets(
                page_size=runtime.settings.polymarket_page_size,
                max_pages=runtime.settings.polymarket_max_pages,
                order=runtime.settings.polymarket_order,
                ascending=runtime.settings.polymarket_sort_ascending,
                closed=runtime.settings.polymarket_closed_filter,
                extra_params=build_filters_from_settings(runtime.settings),
            )
            if runtime.clob_client is not None and markets:
                try:
                    await asyncio.to_thread(
                        merge_clob_markets,
                        markets,
                        runtime.clob_client,
                        max_pages=runtime.settings.polymarket_max_pages,
                        logger=runtime.logger,
                    )
                except (
                    httpx.HTTPError,
                    httpx.RequestError,
                    RuntimeError,
                    ValueError,
                ) as exc:  # pragma: no cover - defensive
                    log_event(
                        runtime.logger,
                        logging.WARNING,
                        event="worker.clob.enrichment_failed",
                        message="failed to enrich markets with clob data",
                        error=str(exc),
                    )
            break
        except (httpx.HTTPError, httpx.RequestError, RuntimeError, ValueError) as exc:
            if attempt >= max_attempts:
                POLYMARKET_FETCH_COUNTER.labels(outcome="error").inc()
                log_event(
                    runtime.logger,
                    logging.ERROR,
                    event="worker.fetch.error",
                    message="failed to fetch markets from polymarket after retries",
                    error=str(exc),
                )
                raise
            delay = base_backoff * (2 ** (attempt - 1))
            if backoff_max > 0:
                delay = min(delay, backoff_max)
            log_event(
                runtime.logger,
                logging.WARNING,
                event="worker.fetch.retry",
                message="retrying polymarket fetch",
                attempt=attempt,
                max_attempts=max_attempts,
                delay_seconds=delay,
                error=str(exc),
            )
            if delay > 0:
                await asyncio.sleep(delay)
    latency_ms = (time.perf_counter() - start) * 1000
    if markets:
        POLYMARKET_FETCH_COUNTER.labels(outcome="success").inc()
        log_event(
            runtime.logger,
            logging.DEBUG,
            event="worker.fetch.success",
            message="retrieved markets from polymarket",
            count=len(markets),
            latency_ms=round(latency_ms, 2),
        )
    else:
        POLYMARKET_FETCH_COUNTER.labels(outcome="empty").inc()
        log_event(
            runtime.logger,
            logging.DEBUG,
            event="worker.fetch.empty",
            message="no markets returned from polymarket feed",
            latency_ms=round(latency_ms, 2),
        )
    return markets, latency_ms
