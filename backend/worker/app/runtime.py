"""Centralizes settings + long-lived clients (Polymarket, CLOB, Goldsky, prover)."""

from __future__ import annotations

import logging
import signal
from typing import Any

import httpx
from py_clob_client.client import ClobClient
from shared.indexers import GoldskyClient
from shared.logging import log_event
from shared.onchain import ConditionalTokensClient

from .config import MissingSettingsError, get_settings, reload_settings, sanitize_settings, validate_required_settings
from .logging_config import setup_logging
from .metrics import POLYMARKET_EMPTY_PAGE_COUNTER, POLYMARKET_RATE_LIMIT_COUNTER, POLYMARKET_RETRY_COUNTER
from .polymarket import AsyncPolymarketClient
from .prover_client import AsyncProverClient

setup_logging("reveal_market.worker")
logger = logging.getLogger("reveal_market.worker")

settings = get_settings()
try:
    validate_required_settings(settings)
except MissingSettingsError as exc:
    logger.error(
        "required environment variables missing",
        extra={"event": "service.config_error", "error": str(exc)},
    )
    raise
_sanitized_config = sanitize_settings(settings)
logger.info("service configuration", extra={"event": "service.config", "config": _sanitized_config})

PROVER_CLIENT: AsyncProverClient | None = None
polymarket_client: AsyncPolymarketClient
clob_client: ClobClient | None = None
conditional_tokens_client: ConditionalTokensClient | None = None
goldsky_client: GoldskyClient | None = None


def _build_polymarket_client() -> AsyncPolymarketClient:
    """Create a Gamma client configured with retry + rate-limit counters."""
    return AsyncPolymarketClient(
        str(settings.polymarket_api_base),
        timeout=settings.polymarket_timeout_seconds,
        request_max_attempts=settings.polymarket_max_retries,
        request_backoff_seconds=settings.polymarket_retry_backoff_seconds,
        request_backoff_max_seconds=settings.polymarket_retry_backoff_max_seconds,
        retry_counter=POLYMARKET_RETRY_COUNTER,
        rate_limit_requests=settings.polymarket_rate_limit_requests,
        rate_limit_window_seconds=settings.polymarket_rate_limit_window_seconds,
        empty_page_tolerance=settings.polymarket_empty_page_tolerance,
        rate_limit_counter=POLYMARKET_RATE_LIMIT_COUNTER,
        empty_page_counter=POLYMARKET_EMPTY_PAGE_COUNTER,
    )


def _build_clob_client() -> ClobClient | None:
    """Create a CLOB client when configured; swallow init errors to keep the worker alive."""
    host = settings.clob_host
    if not host:
        return None
    try:
        return ClobClient(str(host))
    except (RuntimeError, ValueError) as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.clob.error",
            message="failed to initialise clob client",
            error=str(exc),
        )
        return None


def _build_prover_client() -> AsyncProverClient | None:
    """Instantiate the prover client when auto-settlement is enabled."""
    if settings.prover_enabled and settings.prover_base_url:
        return AsyncProverClient(
            base_url=str(settings.prover_base_url),
            timeout_seconds=settings.prover_timeout_seconds,
        )
    return None


def _build_conditional_tokens_client() -> ConditionalTokensClient | None:
    """Instantiate Conditional Tokens RPC client if RPC URL + address are set."""
    rpc_url = settings.polygon_rpc_url or settings.rpc_url
    contract_address = settings.conditional_tokens_address
    if not (rpc_url and contract_address):
        log_event(
            logger,
            logging.DEBUG,
            event="worker.resolution.disabled",
            message="conditional tokens client disabled (missing configuration)",
        )
        return None
    try:
        client = ConditionalTokensClient(str(rpc_url), contract_address)
    except (RuntimeError, ValueError) as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.resolution.error",
            message="failed to initialise conditional tokens client",
            error=str(exc),
        )
        return None
    log_event(
        logger,
        logging.DEBUG,
        event="worker.resolution.enabled",
        message="conditional tokens client initialised",
        contract_address=contract_address,
    )
    return client


def _build_goldsky_client() -> GoldskyClient | None:
    """Instantiate Goldsky subgraph client when provided an endpoint/API key."""
    endpoint = settings.goldsky_subgraph_url
    if not endpoint:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.goldsky.disabled",
            message="goldsky subgraph client disabled (missing endpoint)",
        )
        return None
    api_key = settings.goldsky_api_key.get_secret_value() if settings.goldsky_api_key else None
    try:
        client = GoldskyClient(
            str(endpoint),
            api_key=api_key,
            timeout_seconds=settings.goldsky_timeout_seconds,
        )
    except (ValueError, RuntimeError, httpx.HTTPError, httpx.RequestError) as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.goldsky.error",
            message="failed to initialise goldsky client",
            error=str(exc),
        )
        return None
    log_event(
        logger,
        logging.DEBUG,
        event="worker.goldsky.enabled",
        message="goldsky subgraph client initialised",
    )
    return client


def reload_worker_settings(
    signum: int | None = None, frame: Any | None = None
) -> None:  # pragma: no cover - signal handler
    """Refresh settings + clients on SIGHUP so long-lived processes pick up changes."""
    global settings, polymarket_client, clob_client, conditional_tokens_client, goldsky_client, PROVER_CLIENT
    new_settings = reload_settings()
    try:
        validate_required_settings(new_settings)
    except MissingSettingsError as exc:
        log_event(
            logger,
            logging.ERROR,
            event="worker.config.invalid",
            message="configuration reload failed validation",
            error=str(exc),
        )
        return
    settings = new_settings
    polymarket_client = _build_polymarket_client()
    clob_client = _build_clob_client()
    goldsky_client = _build_goldsky_client()
    conditional_tokens_client = _build_conditional_tokens_client()
    PROVER_CLIENT = _build_prover_client()
    log_event(
        logger,
        logging.DEBUG,
        event="worker.config.reloaded",
        message="worker configuration reloaded",
        signal=signum,
        cache_namespace=getattr(settings, "cache_namespace", "") or "",
    )


polymarket_client = _build_polymarket_client()
clob_client = _build_clob_client()
PROVER_CLIENT = _build_prover_client()
conditional_tokens_client = _build_conditional_tokens_client()
goldsky_client = _build_goldsky_client()

try:  # pragma: no cover - signal availability depends on platform
    signal.signal(signal.SIGHUP, reload_worker_settings)
except (AttributeError, ValueError):
    pass
