from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from shared.logging import log_event
from shared.onchain.conditional_tokens import _derive_winners

try:
    import orjson  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency
    orjson = None  # type: ignore[assignment]


class GoldskyError(RuntimeError):
    """Raised when the downstream Goldsky API returns an error."""


CONDITION_RESOLUTION_QUERY = """
query ConditionResolution($conditionId: Bytes!) {
  conditionResolutions(
    where: { conditionId: $conditionId }
    orderBy: blockNumber
    orderDirection: desc
    first: 1
  ) {
    conditionId
    oracle
    questionId
    payoutNumerators
    transactionHash
    blockNumber
    blockTimestamp
  }
}
"""

ORDERBOOK_QUERY = """
query Orderbooks($first: Int!, $skip: Int!, $ids: [ID!]) {
  orderbooks(
    first: $first
    skip: $skip
    where: { id_in: $ids }
  ) {
    id
    tradesQuantity
    collateralVolume
    scaledCollateralVolume
  }
}
"""


def _normalize_hex(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    if value.startswith("0x") or value.startswith("0X"):
        return value.lower()
    if value:
        return f"0x{value.lower()}"
    return None


def _as_int_list(values: Sequence[Any] | None) -> list[int]:
    numerators: list[int] = []
    if not values:
        return numerators
    for value in values:
        try:
            numerators.append(int(value))
        except (TypeError, ValueError):
            continue
    return numerators


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    timestamp: int | None = None
    if isinstance(value, (int, float)):
        timestamp = int(value)
    elif isinstance(value, str) and value.isdigit():
        timestamp = int(value)
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC)


class GoldskyClient:
    """Lightweight client for Goldsky-hosted GraphQL subgraphs."""

    def __init__(
        self,
        endpoint: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 5.0,
        transport: httpx.BaseTransport | None = None,
        max_attempts: int = 3,
        backoff_seconds: float = 0.2,
        backoff_max_seconds: float = 2.0,
        logger_name: str = "reveal_market.goldsky",
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._transport = transport or httpx.HTTPTransport(retries=0)
        self._client = httpx.Client(timeout=self.timeout_seconds, transport=self._transport)
        self._logger = logging.getLogger(logger_name)
        wait_strategy = wait_random_exponential(multiplier=backoff_seconds, max=backoff_max_seconds)

        def _before_sleep(retry_state):
            error = retry_state.outcome.exception() if retry_state.outcome else None
            log_event(
                self._logger,
                logging.WARNING,
                event="goldsky.request.retry",
                message="retrying goldsky request",
                attempt=retry_state.attempt_number,
                error=str(error) if error else None,
            )

        self._retryer = Retrying(
            stop=stop_after_attempt(max(1, max_attempts)),
            wait=wait_strategy,
            retry=retry_if_exception_type(httpx.HTTPError),
            reraise=True,
            before_sleep=_before_sleep,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(self.endpoint, json=payload, headers=self._headers())
        response.raise_for_status()
        try:
            data = orjson.loads(response.content) if orjson is not None else response.json()
        except ValueError as exc:
            raise GoldskyError(f"invalid response from goldsky: {exc}") from exc
        errors = data.get("errors")
        if errors:
            raise GoldskyError(str(errors))
        return data.get("data") or {}

    def _run_with_retry(self, action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        for attempt in self._retryer:
            with attempt:
                return action()
        raise GoldskyError("goldsky request failed unexpectedly")

    def orderbook_aggregates(self, token_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch basic orderbook aggregates for the given token IDs."""

        if not token_ids:
            return {}
        aggregates: dict[str, dict[str, Any]] = {}

        def _fetch_batch(batch: list[str]) -> list[dict[str, Any]]:
            payload = {
                "query": ORDERBOOK_QUERY,
                "variables": {"first": len(batch), "skip": 0, "ids": batch},
            }
            data = self._run_with_retry(lambda: self._post(payload))
            return data.get("orderbooks") or []

        chunk_size = 40
        for idx in range(0, len(token_ids), chunk_size):
            batch = token_ids[idx : idx + chunk_size]
            try:
                records = _fetch_batch(batch)
            except (
                GoldskyError,
                httpx.HTTPError,
                httpx.RequestError,
                RetryError,
            ) as exc:  # pragma: no cover - network path
                log_event(
                    self._logger,
                    logging.WARNING,
                    event="goldsky.request.failed",
                    message="failed to fetch orderbook batch",
                    error=str(exc),
                )
                continue
            for record in records:
                token_id = str(record.get("id") or "").strip()
                if not token_id:
                    continue
                aggregates[token_id] = record
        return aggregates

    def resolution_summary(
        self,
        condition_id: str,
        outcomes: Sequence[str] | None = None,
        outcome_count_hint: int | None = None,
    ) -> dict[str, Any] | None:
        """Return a resolution snapshot sourced from the Goldsky subgraph."""
        payload = {
            "query": CONDITION_RESOLUTION_QUERY,
            "variables": {"conditionId": condition_id.lower()},
        }
        try:
            data = self._run_with_retry(lambda: self._post(payload))
        except (GoldskyError, httpx.HTTPError, httpx.RequestError, RetryError) as exc:
            log_event(
                self._logger,
                logging.ERROR,
                event="goldsky.request.failed",
                message="failed to query goldsky subgraph",
                error=str(exc),
            )
            raise
        resolutions = data.get("conditionResolutions") or []
        if not resolutions:
            return None
        record = resolutions[0]
        payouts = _as_int_list(record.get("payoutNumerators"))
        if not payouts and isinstance(outcome_count_hint, int) and outcome_count_hint > 0:
            payouts = [0] * outcome_count_hint
        resolved = bool(resolutions)
        block_timestamp = _as_datetime(record.get("blockTimestamp"))
        checked_at = datetime.now(tz=UTC)
        summary = {
            "source": "goldsky_subgraph",
            "conditionId": condition_id.lower(),
            "resolved": resolved,
            "outcomes": list(outcomes) if outcomes else [],
            "payouts": payouts,
            "winners": [],
            "checkedAt": checked_at,
            "oracle": record.get("oracle"),
            "questionId": _normalize_hex(record.get("questionId")),
            "transactionHash": _normalize_hex(record.get("transactionHash")),
            "blockNumber": int(record["blockNumber"]) if record.get("blockNumber") is not None else None,
            "blockTimestamp": block_timestamp,
        }
        summary["winners"] = _derive_winners(summary["payouts"], summary["outcomes"])
        return summary


class AsyncGoldskyClient:
    """Async variant of the Goldsky client (uses httpx.AsyncClient + AsyncRetrying)."""

    def __init__(
        self,
        endpoint: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
        max_attempts: int = 3,
        backoff_seconds: float = 0.2,
        backoff_max_seconds: float = 2.0,
        logger_name: str = "reveal_market.goldsky",
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._transport = transport or httpx.AsyncHTTPTransport(retries=0)
        self._client = httpx.AsyncClient(timeout=self.timeout_seconds, transport=self._transport)
        self._logger = logging.getLogger(logger_name)
        wait_strategy = wait_random_exponential(multiplier=backoff_seconds, max=backoff_max_seconds)

        async def _before_sleep(retry_state):
            error = retry_state.outcome.exception() if retry_state.outcome else None
            log_event(
                self._logger,
                logging.WARNING,
                event="goldsky.request.retry",
                message="retrying goldsky request",
                attempt=retry_state.attempt_number,
                error=str(error) if error else None,
            )

        self._retryer = AsyncRetrying(
            stop=stop_after_attempt(max(1, max_attempts)),
            wait=wait_strategy,
            retry=retry_if_exception_type(httpx.HTTPError),
            reraise=True,
            before_sleep=_before_sleep,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post(self.endpoint, json=payload, headers=self._headers())
        response.raise_for_status()
        try:
            data = orjson.loads(response.content) if orjson is not None else response.json()
        except ValueError as exc:
            raise GoldskyError(f"invalid response from goldsky: {exc}") from exc
        errors = data.get("errors")
        if errors:
            raise GoldskyError(str(errors))
        return data.get("data") or {}

    async def _run_with_retry(self, action: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        async for attempt in self._retryer:
            with attempt:
                return await action()
        raise GoldskyError("goldsky request failed unexpectedly")

    async def resolution_summary(
        self,
        condition_id: str,
        outcomes: Sequence[str] | None = None,
        outcome_count_hint: int | None = None,
    ) -> dict[str, Any] | None:
        """Return a resolution snapshot sourced from the Goldsky subgraph."""

        payload = {
            "query": CONDITION_RESOLUTION_QUERY,
            "variables": {"conditionId": condition_id.lower()},
        }
        try:
            data = await self._run_with_retry(lambda: self._post(payload))
        except (GoldskyError, httpx.HTTPError, httpx.RequestError, RetryError) as exc:
            log_event(
                self._logger,
                logging.ERROR,
                event="goldsky.request.failed",
                message="failed to query goldsky subgraph",
                error=str(exc),
            )
            raise
        resolutions = data.get("conditionResolutions") or []
        if not resolutions:
            return None
        record = resolutions[0]
        payouts = _as_int_list(record.get("payoutNumerators"))
        if not payouts and isinstance(outcome_count_hint, int) and outcome_count_hint > 0:
            payouts = [0] * outcome_count_hint
        resolved = bool(resolutions)
        block_timestamp = _as_datetime(record.get("blockTimestamp"))
        checked_at = datetime.now(tz=UTC)
        summary = {
            "source": "goldsky_subgraph",
            "conditionId": condition_id.lower(),
            "resolved": resolved,
            "outcomes": list(outcomes) if outcomes else [],
            "payouts": payouts,
            "winners": [],
            "checkedAt": checked_at,
            "oracle": record.get("oracle"),
            "questionId": _normalize_hex(record.get("questionId")),
            "transactionHash": _normalize_hex(record.get("transactionHash")),
            "blockNumber": int(record["blockNumber"]) if record.get("blockNumber") is not None else None,
            "blockTimestamp": block_timestamp,
        }
        summary["winners"] = _derive_winners(summary["payouts"], summary["outcomes"])
        return summary

    async def aclose(self) -> None:
        await self._client.aclose()
