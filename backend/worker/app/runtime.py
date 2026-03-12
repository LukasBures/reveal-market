"""Centralizes settings + long-lived clients (Polymarket, CLOB, Goldsky, prover)."""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

import httpx
from py_clob_client.client import ClobClient
from shared.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from shared.indexers import AsyncGoldskyClient
from shared.logging import log_event

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
goldsky_client: AsyncGoldskyClient | None = None
shared_http_clients: dict[float, httpx.AsyncClient] = {}
shared_http_lock = asyncio.Lock()
circuit_breaker: CircuitBreaker | None = None


def _build_polymarket_client() -> AsyncPolymarketClient:
    """Create a Gamma client configured with retry + rate-limit counters."""
    if settings.worker_mock_mode:
        return AsyncPolymarketClient(
            "http://mock-polymarket.local",
            timeout=1.0,
            request_max_attempts=1,
            request_backoff_seconds=0.0,
            request_backoff_max_seconds=0.0,
            retry_counter=POLYMARKET_RETRY_COUNTER,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            empty_page_tolerance=settings.polymarket_empty_page_tolerance,
            rate_limit_counter=POLYMARKET_RATE_LIMIT_COUNTER,
            empty_page_counter=POLYMARKET_EMPTY_PAGE_COUNTER,
        )
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
    if settings.worker_mock_mode:
        return None
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
    """Instantiate the prover client when configured."""
    if settings.prover_base_url:
        secret = settings.prover_shared_secret.get_secret_value() if settings.prover_shared_secret else None
        return AsyncProverClient(
            base_url=str(settings.prover_base_url),
            timeout_seconds=settings.prover_timeout_seconds,
            shared_secret=secret,
        )
    return None


def _build_goldsky_client() -> AsyncGoldskyClient | None:
    """Instantiate async Goldsky subgraph client when provided an endpoint/API key."""
    endpoint = settings.goldsky_subgraph_url
    if not endpoint:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.goldsky.disabled",
            message="goldsky subgraph client disabled (missing endpoint)",
        )
        return None
    try:
        client = AsyncGoldskyClient(
            str(endpoint),
            api_key=None,
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
    global settings, polymarket_client, clob_client, goldsky_client, PROVER_CLIENT, circuit_breaker
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
    PROVER_CLIENT = _build_prover_client()
    if settings.prover_startup_validation_enabled and PROVER_CLIENT is not None:
        try:
            from .proofs import validate_prover_circuit_hash

            asyncio.run(validate_prover_circuit_hash())
        except Exception as exc:  # pragma: no cover - defensive
            log_event(
                logger,
                logging.ERROR,
                event="worker.startup.prover_validation_failed",
                message="prover circuit hash validation failed on reload",
                error=str(exc),
            )
    circuit_breaker = CircuitBreaker(
        None,
        CircuitBreakerConfig(
            key_prefix="reveal_market_worker:circuit",
            failure_threshold=settings.circuit_failure_threshold,
            window_seconds=settings.circuit_window_seconds,
            cooldown_seconds=settings.circuit_cooldown_seconds,
        ),
        logger,
    )
    shared_http_clients.clear()
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
if settings.prover_startup_validation_enabled and PROVER_CLIENT is not None:
    try:
        from .proofs import validate_prover_circuit_hash

        asyncio.run(validate_prover_circuit_hash())
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.ERROR,
            event="worker.startup.prover_validation_failed",
            message="prover circuit hash validation failed",
            error=str(exc),
        )
        raise
goldsky_client = _build_goldsky_client()
circuit_breaker = CircuitBreaker(
    None,
    CircuitBreakerConfig(
        key_prefix="reveal_market_worker:circuit",
        failure_threshold=settings.circuit_failure_threshold,
        window_seconds=settings.circuit_window_seconds,
        cooldown_seconds=settings.circuit_cooldown_seconds,
    ),
    logger,
)

try:  # pragma: no cover - signal availability depends on platform
    signal.signal(signal.SIGHUP, reload_worker_settings)
except (AttributeError, ValueError) as exc:
    log_event(
        logger,
        logging.DEBUG,
        event="worker.signal.sighup_unavailable",
        message="SIGHUP handler unavailable on this platform",
        error=str(exc),
    )


async def get_http_client(timeout: float) -> httpx.AsyncClient:
    timeout_value = float(timeout)
    async with shared_http_lock:
        client = shared_http_clients.get(timeout_value)
        if client is not None and getattr(client, "is_closed", False):
            await client.aclose()
            shared_http_clients.pop(timeout_value, None)
            client = None
        if client is None:
            client = httpx.AsyncClient(timeout=timeout_value)
            shared_http_clients[timeout_value] = client
        return client
