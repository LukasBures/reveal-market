from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import AsyncRetrying, RetryError, retry_if_exception_type, stop_after_attempt, wait_random_exponential

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

CONDITION_QUERY = """
query Condition($conditionId: Bytes!) {
  condition(id: $conditionId) {
    id
    payoutNumerators
    payoutDenominator
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
        resolutions: list[dict[str, Any]] = []
        record: dict[str, Any] = {}
        block_number = None
        block_timestamp = None
        try:
            data = await self._run_with_retry(lambda: self._post(payload))
            resolutions = data.get("conditionResolutions") or []
        except (GoldskyError, httpx.HTTPError, httpx.RequestError, RetryError) as exc:
            log_event(
                self._logger,
                logging.WARNING,
                event="goldsky.resolution.failed",
                message="failed to fetch condition resolutions",
                error=str(exc),
            )
            resolutions = []

        if not resolutions:
            # Fall back to querying the Condition entity directly (pnl-subgraph schema).
            payload["query"] = CONDITION_QUERY
            try:
                data = await self._run_with_retry(lambda: self._post(payload))
            except (GoldskyError, httpx.HTTPError, httpx.RequestError, RetryError) as exc:
                log_event(
                    self._logger,
                    logging.ERROR,
                    event="goldsky.request.failed",
                    message="failed to query goldsky condition",
                    error=str(exc),
                )
                raise
            condition = data.get("condition") or {}
            if not condition:
                return None
            payouts = _as_int_list(condition.get("payoutNumerators"))
            den = condition.get("payoutDenominator")
            if not payouts and isinstance(outcome_count_hint, int) and outcome_count_hint > 0:
                payouts = [0] * outcome_count_hint
            resolved = bool(payouts) or bool(den)
            record = condition
            block_number = None
            block_timestamp = None
        else:
            record = resolutions[0]
            payouts = _as_int_list(record.get("payoutNumerators"))
            if not payouts and isinstance(outcome_count_hint, int) and outcome_count_hint > 0:
                payouts = [0] * outcome_count_hint
            resolved = bool(resolutions)
            block_number = int(record["blockNumber"]) if record.get("blockNumber") is not None else None
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
            "blockNumber": block_number,
            "blockTimestamp": block_timestamp,
        }
        payout_seq: list[int] = list(payouts) if isinstance(payouts, list) else []
        outcomes_seq: list[str] = list(outcomes) if isinstance(outcomes, Sequence) else []
        summary["winners"] = _derive_winners(payout_seq, outcomes_seq)
        return summary

    async def resolution_summary_batch(
        self,
        condition_requests: Sequence[tuple[str, int | None, Sequence[str] | None]],
    ) -> dict[str, dict[str, Any] | None]:
        """Batch variant of resolution_summary using a single GraphQL request with aliases."""

        if not condition_requests:
            return {}

        # Chunk to keep query size reasonable.
        chunk_size = 100
        results: dict[str, dict[str, Any] | None] = {}

        for i in range(0, len(condition_requests), chunk_size):
            chunk = condition_requests[i : i + chunk_size]
            query_parts: list[str] = []
            aliases: list[tuple[str, str]] = []
            for idx, (condition_id, _hint, _outcomes) in enumerate(chunk):
                alias_res = f"c{i + idx}"
                alias_cond = f"c{i + idx}Cond"
                aliases.append((condition_id.lower(), alias_res))
                query_parts.append(
                    f"""{alias_res}: conditionResolutions(
  where: {{ conditionId: "{condition_id.lower()}" }}
  orderBy: blockNumber
  orderDirection: desc
  first: 1
) {{
  conditionId
  oracle
  questionId
  payoutNumerators
  transactionHash
  blockNumber
  blockTimestamp
}}"""
                )
                query_parts.append(
                    f"""{alias_cond}: condition(id: "{condition_id.lower()}") {{
  id
  payoutNumerators
  payoutDenominator
}}"""
                )
            query = "{\n" + "\n".join(query_parts) + "\n}"

            payload = {"query": query}
            try:

                async def _do_post(body: dict[str, Any] = payload) -> dict[str, Any]:
                    return await self._post(body)

                data = await self._run_with_retry(_do_post)
            except (GoldskyError, httpx.HTTPError, httpx.RequestError, RetryError):
                # Mark all in this chunk as None on failure to avoid partial poisoning.
                for condition_id, _alias in aliases:
                    results.setdefault(condition_id, None)
                continue

            for condition_id, alias_res in aliases:
                alias_cond = f"{alias_res}Cond"
                resolutions = data.get(alias_res) or []
                condition = data.get(alias_cond) or {}
                record: dict[str, Any] = {}
                payouts: list[int] = []
                resolved = False
                block_number = None
                block_timestamp = None

                if resolutions:
                    record = resolutions[0]
                    payouts = _as_int_list(record.get("payoutNumerators"))
                    resolved = bool(resolutions)
                    block_number = int(record["blockNumber"]) if record.get("blockNumber") is not None else None
                    block_timestamp = _as_datetime(record.get("blockTimestamp"))
                elif condition:
                    record = condition
                    payouts = _as_int_list(condition.get("payoutNumerators"))
                    den = condition.get("payoutDenominator")
                    resolved = bool(payouts) or bool(den)

                # Fill hint-based padding for payouts when needed.
                hint = next((h for cid, h, _out in chunk if cid.lower() == condition_id), None)
                if not payouts and isinstance(hint, int) and hint > 0:
                    payouts = [0] * hint

                summary = None
                if record:
                    checked_at = datetime.now(tz=UTC)
                    summary = {
                        "source": "goldsky_subgraph",
                        "conditionId": condition_id.lower(),
                        "resolved": resolved,
                        "outcomes": [],
                        "payouts": payouts,
                        "winners": [],
                        "checkedAt": checked_at,
                        "oracle": record.get("oracle"),
                        "questionId": _normalize_hex(record.get("questionId")),
                        "transactionHash": _normalize_hex(record.get("transactionHash")),
                        "blockNumber": block_number,
                        "blockTimestamp": block_timestamp,
                    }
                    summary["winners"] = _derive_winners(payouts, [])

                results[condition_id] = summary

        return results

    async def aclose(self) -> None:
        await self._client.aclose()
