"""Alerting helpers for background task failures."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx
from shared.logging import log_event

from app.runtime import settings

_ALERT_HTTP_CLIENT: httpx.AsyncClient | None = None
_ALERT_CLIENT_LOCK: asyncio.Lock | None = None


async def _get_client() -> httpx.AsyncClient:
    global _ALERT_HTTP_CLIENT, _ALERT_CLIENT_LOCK
    if _ALERT_CLIENT_LOCK is None:
        _ALERT_CLIENT_LOCK = asyncio.Lock()
    async with _ALERT_CLIENT_LOCK:
        if _ALERT_HTTP_CLIENT is None or getattr(_ALERT_HTTP_CLIENT, "is_closed", False):
            _ALERT_HTTP_CLIENT = httpx.AsyncClient(timeout=5.0)
        return _ALERT_HTTP_CLIENT


async def close_alert_client() -> None:
    """Close the shared alerting HTTP client if it exists."""

    global _ALERT_HTTP_CLIENT, _ALERT_CLIENT_LOCK
    if _ALERT_CLIENT_LOCK is None:
        _ALERT_CLIENT_LOCK = asyncio.Lock()
    async with _ALERT_CLIENT_LOCK:
        client = _ALERT_HTTP_CLIENT
        _ALERT_HTTP_CLIENT = None
    if client is not None and not getattr(client, "is_closed", False):
        await client.aclose()


async def alert_background_failure(task: str, exc: Exception, context: dict[str, Any] | None = None) -> None:
    """Emit a structured alert for background failures when configured."""

    webhook = settings.alert_webhook_url
    if not webhook:
        return
    payload = {
        "service": settings.app_name,
        "environment": settings.environment,
        "task": task,
        "error": str(exc),
        "timestamp": int(time.time()),
        "context": context or {},
    }
    headers = {"Content-Type": "application/json"}
    if settings.alert_webhook_token:
        token = settings.alert_webhook_token.get_secret_value()
        headers["Authorization"] = f"Bearer {token}"
    try:
        client = await _get_client()
        resp = await client.post(str(webhook), json=payload, headers=headers)
        if resp.status_code >= 400:
            log_event(
                logging.getLogger("reveal_market.api.alerting"),
                logging.WARNING,
                event="alert.webhook.failed",
                message="alert webhook returned error",
                status_code=resp.status_code,
                response=resp.text[:500],
            )
    except Exception as send_exc:  # pragma: no cover - best-effort alerting
        log_event(
            logging.getLogger("reveal_market.api.alerting"),
            logging.WARNING,
            event="alert.webhook.exception",
            message="alert webhook delivery failed",
            error=str(send_exc),
            payload=json.dumps(payload, default=str)[:500],
        )
