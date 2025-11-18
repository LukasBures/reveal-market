"""Utilities for retrieving and normalising market data from the Polymarket APIs."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError
from shared.categories import canonical_category_from_raw

logger = logging.getLogger("reveal_market.worker.polymarket")


class MarketPayload(BaseModel):
    """Internal representation of a Polymarket market the worker can persist."""

    event_id: str
    title: str
    slug: str | None = None
    category: str | None = None
    metadata_uri: str | None = None
    oracle: str = Field(default="polymarket")
    factory: str | None = None
    market_address: str | None = None
    status: str = Field(default="commit")
    outcomes: list[str] | None = None
    outcome_prices: list[float] | None = None
    tags: list[str] | None = None
    extra_data: dict[str, Any] | None = None
    rake_bps: int | None = None
    condition_id: str | None = None
    question_id: str | None = None
    image_url: str | None = None
    closed: bool | None = None
    uma_resolution_status: str | None = None
    source_updated_at: datetime | None = None
    content_hash: str | None = None
    starts_at: datetime | None = None
    orders_opened_at: datetime | None = None
    resolution_source: str | None = None
    market_maker: str | None = None
    order_min_size: float | None = None
    price_tick_size: float | None = None
    enable_order_book: bool | None = None
    clob_token_ids: list[str] | None = None
    image_variants: list[str] | None = None
    closes_at: datetime | None = None

    @classmethod
    def from_gamma(cls, raw: dict[str, Any]) -> MarketPayload:
        """Normalise a Gamma market payload into `MarketPayload`."""
        if not isinstance(raw, dict):
            raise ValueError("Polymarket record must be a dictionary")

        event_id = raw.get("id")
        if event_id is None:
            raise ValueError("Polymarket record is missing an id")

        title = raw.get("question") or raw.get("title") or raw.get("name") or f"Market {event_id}"
        slug = raw.get("slug")
        condition_id = raw.get("conditionId")
        question_id = raw.get("questionID") or raw.get("questionId")
        image_url = raw.get("image") or raw.get("imageUrl") or raw.get("imageURL")
        closed = raw.get("closed")
        uma_status = _extract_uma_status(raw)

        outcomes = _extract_outcomes(raw.get("outcomes"))
        outcome_prices = _extract_prices(raw.get("outcomePrices"))
        category = _derive_category(raw)
        status = _derive_status(closed, uma_status)
        tags = _extract_tags(raw.get("tags"))
        canonical_category = canonical_category_from_raw(category, tags=tags)
        if canonical_category:
            _, category = canonical_category
        updated_at = _extract_updated_at(raw)
        closes_at = _extract_close_time(raw)
        starts_at = _extract_timestamp_candidate(
            raw.get("startDate") or raw.get("startTime") or raw.get("eventStartTime") or raw.get("eventStartTimestamp"),
        )
        orders_opened_at = _extract_timestamp_candidate(raw.get("acceptingOrdersTimestamp"))
        resolution_source = _clean_string(raw.get("resolutionSource")) or _extract_resolution_source_from_events(
            raw.get("events")
        )
        market_maker = _clean_string(raw.get("marketMakerAddress"))
        enable_order_book = raw.get("enableOrderBook") if isinstance(raw.get("enableOrderBook"), bool) else None
        order_min_size = _coerce_float(raw.get("orderMinSize"))
        price_tick_size = _coerce_float(raw.get("orderPriceMinTickSize"))
        clob_token_ids = _extract_clob_ids(raw.get("clobTokenIds"))
        image_variants = _collect_images(raw)

        extra_data: dict[str, Any] = {"gamma": raw}
        hash_payload = {
            "event_id": str(event_id),
            "title": str(title),
            "slug": str(slug) if slug is not None else None,
            "category": category,
            "status": status,
            "outcomes": outcomes,
            "outcome_prices": outcome_prices,
            "tags": tags,
            "closed": bool(closed) if isinstance(closed, bool) else None,
            "image_url": str(image_url) if image_url is not None else None,
            "uma_resolution_status": str(uma_status) if uma_status is not None else None,
            "condition_id": str(condition_id) if condition_id is not None else None,
            "question_id": str(question_id) if question_id is not None else None,
            "closes_at": closes_at.isoformat() if isinstance(closes_at, datetime) else None,
            "starts_at": starts_at.isoformat() if isinstance(starts_at, datetime) else None,
            "orders_opened_at": orders_opened_at.isoformat() if isinstance(orders_opened_at, datetime) else None,
            "resolution_source": resolution_source,
            "market_maker": market_maker,
            "order_min_size": order_min_size,
            "price_tick_size": price_tick_size,
            "enable_order_book": enable_order_book,
            "clob_token_ids": clob_token_ids,
            "image_variants": image_variants,
        }

        return cls(
            event_id=str(event_id),
            title=str(title),
            slug=str(slug) if slug is not None else None,
            category=category,
            metadata_uri=None,
            oracle="polymarket",
            factory=None,
            market_address=None,
            status=status,
            tags=tags,
            outcomes=outcomes,
            outcome_prices=outcome_prices,
            extra_data=extra_data,
            rake_bps=None,
            condition_id=str(condition_id) if condition_id is not None else None,
            question_id=str(question_id) if question_id is not None else None,
            image_url=str(image_url) if image_url is not None else None,
            closed=bool(closed) if isinstance(closed, bool) else None,
            uma_resolution_status=str(uma_status) if uma_status is not None else None,
            source_updated_at=updated_at,
            content_hash=_compute_market_hash(hash_payload),
            closes_at=closes_at,
            starts_at=starts_at,
            orders_opened_at=orders_opened_at,
            resolution_source=resolution_source,
            market_maker=market_maker,
            order_min_size=order_min_size,
            price_tick_size=price_tick_size,
            enable_order_book=enable_order_book,
            clob_token_ids=clob_token_ids,
            image_variants=image_variants,
        )


class PolymarketClient:
    """Lightweight client for the Polymarket Gamma REST API."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        request_max_attempts: int = 1,
        request_backoff_seconds: float = 0.2,
        request_backoff_max_seconds: float | None = None,
        retry_counter: Any | None = None,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.timeout = timeout
        self._transport = transport
        self._request_max_attempts = max(1, int(request_max_attempts))
        self._request_backoff_seconds = request_backoff_seconds if request_backoff_seconds > 0 else 0.1
        self._request_backoff_max_seconds = (
            request_backoff_max_seconds if request_backoff_max_seconds and request_backoff_max_seconds > 0 else None
        )
        self._retryer = None
        self._retry_counter = retry_counter

    def fetch_markets(  # noqa: C901
        self,
        *,
        page_size: int = 100,
        max_pages: int | None = None,
        order: str = "id",
        ascending: bool = False,
        closed: bool | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> list[MarketPayload]:
        """Walk the offset-based API, returning a list of validated markets."""
        markets: list[MarketPayload] = []
        offset = 0
        page = 0

        with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
            while True:
                params: dict[str, Any] = {
                    "limit": page_size,
                    "offset": offset,
                    "order": order,
                    "ascending": str(ascending).lower(),
                }
                if closed is not None:
                    params["closed"] = str(closed).lower()
                if extra_params:
                    params.update({k: v for k, v in extra_params.items() if v is not None})

                url = f"{self.base_url}/markets"
                request_callable = partial(_request_page, client, url, params.copy())
                try:
                    response = self._send_with_retry(request_callable)
                    payload = response.json()
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.error("failed to fetch polymarket page offset=%s: %s", offset, exc)
                    raise

                if not isinstance(payload, list) or not payload:
                    break

                for raw in payload:
                    if not isinstance(raw, dict):
                        continue
                    try:
                        markets.append(MarketPayload.from_gamma(raw))
                    except (ValidationError, ValueError) as exc:
                        logger.warning("skipping polymarket record: %s", exc)

                offset += len(payload)
                page += 1

                if max_pages is not None and page >= max_pages:
                    break
                if len(payload) < page_size:
                    break

        return markets

    def _send_with_retry(self, action: Callable[[], httpx.Response]) -> httpx.Response:
        retryer = self._build_retryer()
        try:
            if retryer is None:
                response = action()
            else:
                response = retryer(action)
            self._record_retry_metric("success")
            return response
        except Exception:
            self._record_retry_metric("failed")
            raise

    def _build_retryer(self):
        if self._request_max_attempts <= 1:
            return None
        if self._retryer is not None:
            return self._retryer
        try:
            from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential
        except ModuleNotFoundError:  # pragma: no cover - defensive
            return None

        wait_kwargs = {"multiplier": self._request_backoff_seconds, "min": self._request_backoff_seconds}
        if self._request_backoff_max_seconds:
            wait_kwargs["max"] = self._request_backoff_max_seconds

        def _log_retry(retry_state):
            exc = retry_state.outcome.exception() if retry_state.outcome else None
            self._record_retry_metric("retry")
            logger.warning(
                "retrying polymarket request",
                extra={
                    "attempt": retry_state.attempt_number,
                    "max_attempts": self._request_max_attempts,
                    "error": str(exc) if exc else None,
                },
            )

        self._retryer = Retrying(
            stop=stop_after_attempt(self._request_max_attempts),
            wait=wait_exponential(**wait_kwargs),
            retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
            before_sleep=_log_retry,
            reraise=True,
        )
        return self._retryer

    def _record_retry_metric(self, outcome: str) -> None:
        counter = self._retry_counter
        if counter is None:
            return
        try:
            counter.labels(outcome=outcome).inc()
        except Exception:  # pragma: no cover - metrics failures should not break ingestion
            logger.debug("failed to record polymarket retry metric", extra={"metric_outcome": outcome})


def _request_page(client: httpx.Client, url: str, params: dict[str, Any]) -> httpx.Response:
    response = client.get(url, params=params)
    response.raise_for_status()
    return response


def _extract_outcomes(outcomes: Any) -> list[str] | None:
    sequence = _coerce_sequence(outcomes)
    if not sequence:
        return None
    cleaned: list[str] = []
    for item in sequence:
        if isinstance(item, str):
            cleaned.append(item)
        elif isinstance(item, dict):
            label = item.get("name") or item.get("outcome") or item.get("label")
            if label is not None:
                cleaned.append(str(label))
    return cleaned or None


def _extract_prices(prices: Any) -> list[float] | None:
    sequence = _coerce_sequence(prices)
    if not sequence:
        return None
    cleaned: list[float] = []
    for value in sequence:
        if isinstance(value, (int, float)):
            cleaned.append(float(value))
        elif isinstance(value, str):
            try:
                cleaned.append(float(value))
            except ValueError:
                continue
    return cleaned or None


def _clean_string(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            return cleaned
    return None


def _category_from_tags(raw: dict[str, Any]) -> str | None:
    tags = raw.get("tags")
    if not isinstance(tags, list):
        return None
    for entry in tags:
        if isinstance(entry, str):
            candidate = _clean_string(entry)
            if candidate:
                return candidate
        elif isinstance(entry, dict):
            candidate = _clean_string(entry.get("slug") or entry.get("name") or entry.get("label"))
            if candidate:
                return candidate
    return None


def _category_from_field(raw: dict[str, Any]) -> str | None:
    return _clean_string(raw.get("category"))


def _category_from_events(raw: dict[str, Any]) -> str | None:
    events = raw.get("events")
    if not isinstance(events, list):
        return None

    def _from_event(event: dict[str, Any]) -> str | None:
        series = event.get("series")
        if isinstance(series, list):
            for item in series:
                if isinstance(item, dict):
                    candidate = _clean_string(item.get("title") or item.get("slug"))
                    if candidate:
                        return candidate
        keys = (
            "seriesSlug",
            "series_slug",
            "seriesTicker",
            "seriesTickerSlug",
            "seriesTickerLabel",
            "ticker",
            "slug",
            "title",
            "groupItemTitle",
        )
        for key in keys:
            candidate = _clean_string(event.get(key))
            if candidate:
                return candidate
        return None

    for event in events:
        if isinstance(event, dict):
            candidate = _from_event(event)
            if candidate:
                return candidate
    return None


def _category_from_series(raw: dict[str, Any]) -> str | None:
    series = raw.get("series")
    if not isinstance(series, list):
        return None
    for entry in series:
        if isinstance(entry, dict):
            candidate = _clean_string(entry.get("title") or entry.get("slug"))
            if candidate:
                return candidate
    return None


def _derive_category(raw: dict[str, Any]) -> str | None:
    for extractor in (
        _category_from_tags,
        _category_from_field,
        _category_from_events,
        _category_from_series,
    ):
        category = extractor(raw)
        if category:
            return category
    return None


def _extract_tags(tags: Any) -> list[str] | None:
    if not isinstance(tags, list):
        return None
    result: list[str] = []
    for entry in tags:
        if isinstance(entry, str):
            cleaned = entry.strip()
            if cleaned:
                result.append(cleaned)
        elif isinstance(entry, dict):
            candidate = entry.get("slug") or entry.get("name") or entry.get("label")
            if isinstance(candidate, str) and candidate.strip():
                result.append(candidate.strip())
    return result or None


def _derive_status(closed: Any, resolution_status: Any) -> str:
    if isinstance(resolution_status, str):
        lowered = resolution_status.lower()
        if lowered in {"resolved", "settled", "confirmed", "resolved_final"}:
            return "settled"
    if isinstance(closed, bool) and closed:
        return "locked"
    return "commit"


def _extract_updated_at(raw: dict[str, Any]) -> datetime | None:
    candidate_keys = [
        "updatedAt",
        "updated_at",
        "updatedTime",
        "updated_time",
        "lastUpdated",
        "last_updated",
        "modified",
        "modifiedAt",
    ]
    for key in candidate_keys:
        if key in raw:
            ts = _coerce_timestamp(raw[key])
            if ts is not None:
                return ts
    return None


def _extract_close_time(raw: dict[str, Any]) -> datetime | None:
    candidate_keys = [
        "closesAt",
        "closes_at",
        "closeTime",
        "close_time",
        "closeDate",
        "close_date",
        "endDate",
        "end_date",
        "resolutionTime",
        "resolveTime",
        "lockTime",
        "lockedAt",
    ]
    for key in candidate_keys:
        if key in raw:
            ts = _coerce_timestamp(raw[key])
            if ts is not None:
                return ts
    return None


def _coerce_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1_000_000_000_000:  # assume milliseconds
            seconds = seconds / 1000.0
        return datetime.fromtimestamp(seconds, tz=UTC)
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.isdigit():
            return _coerce_timestamp(int(candidate))
        try:
            normalized = candidate.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            try:
                numeric = float(candidate)
            except ValueError:
                return None
            return _coerce_timestamp(numeric)
    return None


def _extract_timestamp_candidate(value: Any) -> datetime | None:
    if value is None:
        return None
    return _coerce_timestamp(value)


def _extract_resolution_source_from_events(events: Any) -> str | None:
    if not isinstance(events, list):
        return None
    for event in events:
        if isinstance(event, dict):
            candidate = _clean_string(event.get("resolutionSource"))
            if candidate:
                return candidate
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _extract_clob_ids(raw_ids: Any) -> list[str] | None:
    sequence = _coerce_sequence(raw_ids)
    if not sequence:
        return None
    values: list[str] = []
    for entry in sequence:
        if isinstance(entry, str):
            candidate = entry.strip()
            if candidate:
                values.append(candidate)
    return values or None


def _collect_images(raw: dict[str, Any]) -> list[str] | None:
    images: list[str] = []
    candidates = [raw.get("image"), raw.get("icon"), raw.get("imageUrl"), raw.get("imageURL"), raw.get("coverImage")]
    events = raw.get("events")
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict):
                candidates.extend([event.get("image"), event.get("icon")])
    seen = set()
    for candidate in candidates:
        cleaned = _clean_string(candidate)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            images.append(cleaned)
    return images or None


def _coerce_sequence(value: Any) -> list[Any] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        if isinstance(parsed, list):
            return parsed
        return [parsed]
    return None


def _extract_uma_status(raw: dict[str, Any]) -> str | None:
    direct = _clean_string(raw.get("umaResolutionStatus")) or _clean_string(raw.get("polymarketEventStatus"))
    if direct:
        return direct
    sequence = _coerce_sequence(raw.get("umaResolutionStatuses"))
    if not sequence:
        return None
    for entry in sequence:
        if isinstance(entry, str):
            candidate = _clean_string(entry)
            if candidate:
                return candidate
        elif isinstance(entry, dict):
            for key in ("status", "state", "label", "value"):
                candidate = _clean_string(entry.get(key))
                if candidate:
                    return candidate
    return None


def _compute_market_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    return value
