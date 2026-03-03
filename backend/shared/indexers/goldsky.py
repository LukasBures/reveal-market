from __future__ import annotations

import logging
import time
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

try:
    from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge
except ImportError:  # pragma: no cover - optional dependency

    class _CounterStub:
        def __init__(self, *args, **kwargs):
            pass

        def labels(self, **kwargs):
            return self

        @staticmethod
        def inc(amount: float = 1.0) -> None:
            return None

    class _GaugeStub:
        def __init__(self, *args, **kwargs):
            pass

        def labels(self, **kwargs):
            return self

        @staticmethod
        def set(value: float) -> None:
            return None

    class _CollectorRegistryStub:
        pass

    Counter = _CounterStub  # type: ignore[misc,assignment]
    Gauge = _GaugeStub  # type: ignore[misc,assignment]
    CollectorRegistry = _CollectorRegistryStub  # type: ignore[misc,assignment]
    REGISTRY = None  # type: ignore[assignment]


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


def _safe_counter(name: str, documentation: str, labelnames: list[str]) -> Counter:
    registry = REGISTRY
    try:
        return Counter(name, documentation, labelnames, registry=registry)
    except ValueError:
        existing = getattr(registry, "_names_to_collectors", {}).get(name) if registry else None
        if isinstance(existing, Counter):
            return existing
        return Counter(name, documentation, labelnames, registry=CollectorRegistry())


def _safe_gauge(name: str, documentation: str, labelnames: list[str]) -> Gauge:
    registry = REGISTRY
    try:
        return Gauge(name, documentation, labelnames, registry=registry)
    except ValueError:
        existing = getattr(registry, "_names_to_collectors", {}).get(name) if registry else None
        if isinstance(existing, Gauge):
            return existing
        return Gauge(name, documentation, labelnames, registry=CollectorRegistry())


GOLDSKY_REQUEST_COUNTER = _safe_counter(
    "goldsky_requests_total",
    "Outcome of Goldsky requests",
    ["phase", "result"],
)

GOLDSKY_FAILURE_SUPPRESSED_COUNTER = _safe_counter(
    "goldsky_failure_logs_suppressed_total",
    "Suppressed Goldsky failure logs due to cooldown",
    ["event"],
)

GOLDSKY_DEGRADED_GAUGE = _safe_gauge(
    "goldsky_degraded",
    "1 when Goldsky lookups are degraded (latest request path failed), 0 when healthy",
    [],
)


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


def _is_missing_condition_resolutions_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "conditionresolutions" in message and ("no field" in message or "cannot query field" in message)


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
        self._supports_condition_resolutions: bool | None = None
        self._logged_condition_resolution_schema_warning = False
        self._degraded = False
        self._failure_log_cooldown_seconds = 60.0
        self._failure_log_state: dict[str, tuple[float, int]] = {}
        GOLDSKY_DEGRADED_GAUGE.set(0)
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

    def _mark_success(self, *, phase: str) -> None:
        GOLDSKY_REQUEST_COUNTER.labels(phase=phase, result="success").inc()
        if self._degraded:
            self._degraded = False
            GOLDSKY_DEGRADED_GAUGE.set(0)
            suppressed_total = sum(suppressed for _last, suppressed in self._failure_log_state.values())
            if suppressed_total > 0:
                log_event(
                    self._logger,
                    logging.INFO,
                    event="goldsky.recovered",
                    message="goldsky request path recovered",
                    suppressed_failures=suppressed_total,
                )
            self._failure_log_state.clear()

    def _log_failure_with_cooldown(
        self,
        *,
        phase: str,
        event: str,
        message: str,
        error: str,
        level: int = logging.WARNING,
    ) -> None:
        GOLDSKY_REQUEST_COUNTER.labels(phase=phase, result="failure").inc()
        self._degraded = True
        GOLDSKY_DEGRADED_GAUGE.set(1)

        now = time.monotonic()
        last_emit, suppressed = self._failure_log_state.get(event, (float("-inf"), 0))
        if now - last_emit < self._failure_log_cooldown_seconds:
            self._failure_log_state[event] = (last_emit, suppressed + 1)
            GOLDSKY_FAILURE_SUPPRESSED_COUNTER.labels(event=event).inc()
            return

        self._failure_log_state[event] = (now, 0)
        extra_fields: dict[str, Any] = {"error": error}
        if suppressed > 0:
            extra_fields["suppressed_since_last"] = suppressed
        log_event(
            self._logger,
            level,
            event=event,
            message=message,
            **extra_fields,
        )

    def _log_condition_resolution_schema_warning_once(self, *, error: str) -> None:
        if self._logged_condition_resolution_schema_warning:
            return
        self._logged_condition_resolution_schema_warning = True
        log_event(
            self._logger,
            logging.WARNING,
            event="goldsky.resolution.schema_mismatch",
            message="conditionResolutions field missing; falling back to condition query",
            error=error,
        )

    @staticmethod
    def _build_batch_query(
        chunk: Sequence[tuple[str, int | None, Sequence[str] | None]],
        *,
        offset: int,
        include_resolutions: bool,
    ) -> tuple[str, list[tuple[str, str | None, str]]]:
        query_parts: list[str] = []
        aliases: list[tuple[str, str | None, str]] = []
        for idx, (condition_id, _hint, _outcomes) in enumerate(chunk):
            condition_key = condition_id.lower()
            alias_res = f"c{offset + idx}" if include_resolutions else None
            alias_cond = f"c{offset + idx}Cond"
            aliases.append((condition_key, alias_res, alias_cond))
            if alias_res:
                query_parts.append(
                    f"""{alias_res}: conditionResolutions(
  where: {{ conditionId: "{condition_key}" }}
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
                f"""{alias_cond}: condition(id: "{condition_key}") {{
  id
  payoutNumerators
  payoutDenominator
}}"""
            )
        query = "{\n" + "\n".join(query_parts) + "\n}"
        return query, aliases

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
        if self._supports_condition_resolutions is not False:
            try:
                data = await self._run_with_retry(lambda: self._post(payload))
                self._supports_condition_resolutions = True
                resolutions = data.get("conditionResolutions") or []
                self._mark_success(phase="resolution_summary_condition_resolutions")
            except (GoldskyError, httpx.HTTPError, httpx.RequestError, RetryError) as exc:
                if _is_missing_condition_resolutions_error(exc):
                    self._supports_condition_resolutions = False
                    self._log_condition_resolution_schema_warning_once(error=str(exc))
                else:
                    self._log_failure_with_cooldown(
                        phase="resolution_summary_condition_resolutions",
                        event="goldsky.resolution.failed",
                        message="failed to fetch condition resolutions",
                        error=str(exc),
                        level=logging.WARNING,
                    )
                resolutions = []

        if not resolutions:
            # Fall back to querying the Condition entity directly (pnl-subgraph schema).
            payload["query"] = CONDITION_QUERY
            try:
                data = await self._run_with_retry(lambda: self._post(payload))
                self._mark_success(phase="resolution_summary_condition")
            except (GoldskyError, httpx.HTTPError, httpx.RequestError, RetryError) as exc:
                self._log_failure_with_cooldown(
                    phase="resolution_summary_condition",
                    event="goldsky.request.failed",
                    message="failed to query goldsky condition",
                    error=str(exc),
                    level=logging.ERROR,
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
            hints = {condition_id.lower(): hint for condition_id, hint, _outcomes in chunk}
            include_resolutions = self._supports_condition_resolutions is not False
            query, aliases = self._build_batch_query(chunk, offset=i, include_resolutions=include_resolutions)
            payload = {"query": query}
            try:

                async def _do_post(body: dict[str, Any] = payload) -> dict[str, Any]:
                    return await self._post(body)

                data = await self._run_with_retry(_do_post)
                if include_resolutions:
                    self._supports_condition_resolutions = True
                phase = (
                    "resolution_summary_batch_resolutions"
                    if include_resolutions
                    else "resolution_summary_batch_condition"
                )
                self._mark_success(phase=phase)
            except (GoldskyError, httpx.HTTPError, httpx.RequestError, RetryError) as exc:
                if include_resolutions and _is_missing_condition_resolutions_error(exc):
                    self._supports_condition_resolutions = False
                    self._log_condition_resolution_schema_warning_once(error=str(exc))
                    fallback_query, aliases = self._build_batch_query(chunk, offset=i, include_resolutions=False)
                    fallback_payload = {"query": fallback_query}
                    try:

                        async def _do_post_fallback(body: dict[str, Any] = fallback_payload) -> dict[str, Any]:
                            return await self._post(body)

                        data = await self._run_with_retry(_do_post_fallback)
                        self._mark_success(phase="resolution_summary_batch_condition")
                    except (GoldskyError, httpx.HTTPError, httpx.RequestError, RetryError) as fallback_exc:
                        self._log_failure_with_cooldown(
                            phase="resolution_summary_batch_condition",
                            event="goldsky.batch.request.failed",
                            message="failed to query goldsky batch fallback condition payload",
                            error=str(fallback_exc),
                            level=logging.ERROR,
                        )
                        for condition_id, _alias_res, _alias_cond in aliases:
                            results.setdefault(condition_id, None)
                        continue
                else:
                    phase = (
                        "resolution_summary_batch_resolutions"
                        if include_resolutions
                        else "resolution_summary_batch_condition"
                    )
                    self._log_failure_with_cooldown(
                        phase=phase,
                        event="goldsky.batch.request.failed",
                        message="failed to query goldsky batch payload",
                        error=str(exc),
                        level=logging.ERROR,
                    )
                    # Mark all in this chunk as None on failure to avoid partial poisoning.
                    for condition_id, _alias_res, _alias_cond in aliases:
                        results.setdefault(condition_id, None)
                    continue

            for condition_id, alias_res, alias_cond in aliases:
                resolutions = data.get(alias_res) or [] if alias_res else []
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
                hint = hints.get(condition_id)
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
