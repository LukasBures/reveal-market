"""Utilities for retrieving and normalising market data from the Polymarket APIs."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import deque
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from functools import partial
from typing import Any

import httpx
from py_clob_client.client import ClobClient
from py_clob_client.constants import END_CURSOR
from pydantic import BaseModel, Field, ValidationError
from shared.categories import canonical_category_from_raw
from shared.polymarket import build_polymarket_markets_url

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
    outcomes: list[str] | None = None  # transient; persisted into market_outcomes
    outcome_prices: list[float] | None = None  # transient; persisted into market_outcomes
    tags: list[str] | None = None  # transient; persisted into market_tags
    clob_token_ids: list[str] | None = None  # transient; persisted into market_clob_tokens
    gamma_raw: dict[str, Any] | None = None
    gamma_metadata: dict[str, Any] | None = None
    gamma_events: list[dict[str, Any]] | None = None
    group_slug: str | None = None
    group_position: int | None = None
    group_item_title: str | None = None
    group_item_threshold: float | None = None
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
    image_variants: list[str] | None = None
    featured: bool = False
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    open_interest: float | None = None
    volume: float | None = None
    closes_at: datetime | None = None
    liquidity_usd: float | None = None
    volume_24h_usd: float | None = None
    orderbook_volume_usd: float | None = None
    trades_quantity: int | None = None

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
        featured = True if raw.get("featured") is True else False
        resolution_source = _clean_string(raw.get("resolutionSource")) or _extract_resolution_source_from_events(
            raw.get("events")
        )
        market_maker = _clean_string(raw.get("marketMakerAddress"))
        enable_order_book = raw.get("enableOrderBook") if isinstance(raw.get("enableOrderBook"), bool) else None
        order_min_size = _coerce_float(raw.get("orderMinSize"))
        price_tick_size = _coerce_float(raw.get("orderPriceMinTickSize"))
        clob_token_ids = _extract_clob_ids(raw.get("clobTokenIds"))
        image_variants = _collect_images(raw)
        group_item_title = _clean_string(raw.get("groupItemTitle") or raw.get("group_item_title"))
        raw_group_threshold = raw.get("groupItemThreshold") or raw.get("group_item_threshold")
        group_item_threshold = _parse_group_threshold(raw_group_threshold)
        group_position = None
        if group_item_threshold is not None:
            try:
                group_position = int(group_item_threshold)
            except (TypeError, ValueError, OverflowError):
                group_position = None
        group_slug = _derive_group_slug(slug, raw.get("question"), group_item_title)

        gamma_metadata = {
            "gamma_id": str(event_id),
            "question": raw.get("question"),
            "slug": slug,
            "resolution_source": resolution_source,
            "end_date": _extract_timestamp_candidate(raw.get("endDate")),
            "start_date": starts_at,
            "image": image_url,
            "icon": raw.get("icon"),
            "description": raw.get("description"),
            "enable_order_book": enable_order_book,
            "order_price_min_tick_size": price_tick_size,
            "order_min_size": order_min_size,
            "clob_token_id_yes": clob_token_ids[0] if clob_token_ids and clob_token_ids[0] is not None else None,
            "clob_token_id_no": clob_token_ids[1] if clob_token_ids and len(clob_token_ids) > 1 else None,
            "group_item_title": group_item_title,
            "group_item_threshold": raw_group_threshold if raw_group_threshold is not None else group_item_threshold,
            "group_slug": group_slug,
            "featured": featured,
            "best_bid": None,
            "best_ask": None,
            "spread": None,
            "volume": None,
        }
        gamma_events = []
        open_interest = _coerce_float(raw.get("openInterest") or raw.get("open_interest"))
        for event in raw.get("events") or []:
            if isinstance(event, dict):
                gamma_events.append(event)
        if open_interest is not None and not gamma_events:
            gamma_events.append({"open_interest": open_interest})

        liquidity_usd = _extract_liquidity(raw)
        volume_24h_usd = _extract_volume_24h(raw)
        orderbook_volume_usd = _extract_orderbook_volume(raw)
        trades_quantity = _extract_trades_quantity(raw)
        best_bid = _coerce_float(raw.get("bestBid") or raw.get("bestBidYes") or raw.get("best_bid"))
        best_ask = _coerce_float(raw.get("bestAsk") or raw.get("bestAskYes") or raw.get("best_ask"))
        spread = _coerce_float(raw.get("spread"))
        volume_total = _coerce_float(raw.get("volume"))
        if gamma_metadata is not None:
            gamma_metadata["best_bid"] = best_bid
            gamma_metadata["best_ask"] = best_ask
            gamma_metadata["spread"] = spread
            gamma_metadata["volume"] = volume_total

        market = cls(
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
            gamma_raw=raw,
            gamma_metadata=gamma_metadata,
            gamma_events=gamma_events or None,
            rake_bps=None,
            condition_id=str(condition_id) if condition_id is not None else None,
            question_id=str(question_id) if question_id is not None else None,
            image_url=str(image_url) if image_url is not None else None,
            closed=bool(closed) if isinstance(closed, bool) else None,
            uma_resolution_status=str(uma_status) if uma_status is not None else None,
            source_updated_at=updated_at,
            content_hash=None,
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
            featured=featured,
            liquidity_usd=liquidity_usd,
            volume_24h_usd=volume_24h_usd,
            orderbook_volume_usd=orderbook_volume_usd,
            trades_quantity=trades_quantity,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            open_interest=open_interest,
            volume=volume_total,
            group_slug=group_slug,
            group_position=group_position,
            group_item_title=group_item_title,
            group_item_threshold=group_item_threshold,
        )
        market.content_hash = _compute_market_hash(_build_market_hash_payload(market))
        return market


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
        rate_limit_requests: int | None = None,
        rate_limit_window_seconds: float | None = None,
        empty_page_tolerance: int = 0,
        rate_limit_counter: Any | None = None,
        empty_page_counter: Any | None = None,
    ) -> None:
        raw_base = str(base_url)
        self.base_url = raw_base.rstrip("/")
        self._markets_url = build_polymarket_markets_url(raw_base)
        self.timeout = timeout
        self._transport = transport
        self._request_max_attempts = max(1, int(request_max_attempts))
        self._request_backoff_seconds = request_backoff_seconds if request_backoff_seconds > 0 else 0.1
        self._request_backoff_max_seconds = (
            request_backoff_max_seconds if request_backoff_max_seconds and request_backoff_max_seconds > 0 else None
        )
        self._retryer = None
        self._retry_counter = retry_counter
        self._rate_limit_counter = rate_limit_counter
        self._empty_page_counter = empty_page_counter
        self._rate_limiter = _RateLimiter(rate_limit_requests, rate_limit_window_seconds)
        self._empty_page_tolerance = max(0, empty_page_tolerance)

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
        for page in self.fetch_markets_paginated(
            page_size=page_size,
            max_pages=max_pages,
            order=order,
            ascending=ascending,
            closed=closed,
            extra_params=extra_params,
        ):
            markets.extend(page)
        return markets

    def fetch_markets_paginated(
        self,
        *,
        page_size: int = 100,
        max_pages: int | None = None,
        order: str = "id",
        ascending: bool = False,
        closed: bool | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> Iterator[list[MarketPayload]]:
        """Yield Polymarket markets page-by-page to reduce peak memory."""

        offset = 0
        page = 0
        empty_pages = 0
        total_records: int | None = None

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

                url = self._markets_url
                request_callable = partial(self._request_page, client, url, params.copy())
                try:
                    response = self._send_with_retry(request_callable)
                    payload = response.json()
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.error("failed to fetch polymarket page offset=%s: %s", offset, exc)
                    raise

                meta_total = _extract_meta_total(payload)
                if isinstance(meta_total, int) and meta_total >= 0:
                    total_records = meta_total
                records = _extract_page_records(payload)
                if not records:
                    empty_pages += 1
                    logger.debug(
                        "polymarket page contained no records",
                        extra={"offset": offset, "empty_pages": empty_pages},
                    )
                    self._record_empty_page()
                    if (
                        total_records is not None
                        and offset < total_records
                        and empty_pages <= self._empty_page_tolerance
                    ):
                        offset += page_size
                        continue
                    if empty_pages <= self._empty_page_tolerance:
                        offset += page_size
                        continue
                    break
                empty_pages = 0

                page_payloads: list[MarketPayload] = []
                for raw in records:
                    try:
                        page_payloads.append(MarketPayload.from_gamma(raw))
                    except (ValidationError, ValueError) as exc:
                        logger.warning("skipping polymarket record: %s", exc)

                yield page_payloads

                offset += len(records)
                page += 1

                if max_pages is not None and page >= max_pages:
                    break
                if total_records is not None and offset >= total_records:
                    break
                if len(records) < page_size:
                    break

    def _request_page(self, client: httpx.Client, url: str, params: dict[str, Any]) -> httpx.Response:
        self._rate_limiter.acquire()
        response = client.get(url, params=params)
        if response.status_code == 429:
            self._record_rate_limit()
            logger.warning(
                "polymarket rate limit encountered",
                extra={"params": params, "status_code": response.status_code},
            )
        response.raise_for_status()
        return response

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

    def _record_rate_limit(self) -> None:
        counter = getattr(self, "_rate_limit_counter", None)
        if counter is None:
            return
        try:
            counter.labels(outcome="rate_limited").inc()
        except Exception:  # pragma: no cover
            logger.debug("failed to record polymarket rate limit metric")

    def _record_empty_page(self) -> None:
        counter = getattr(self, "_empty_page_counter", None)
        if counter is None:
            return
        try:
            counter.labels(outcome="empty").inc()
        except Exception:  # pragma: no cover
            logger.debug("failed to record polymarket empty page metric")


class _RateLimiter:
    def __init__(self, max_requests: int | None, window_seconds: float | None) -> None:
        self.max_requests = max_requests if max_requests and max_requests > 0 else None
        self.window_seconds = window_seconds if window_seconds and window_seconds > 0 else None
        self._events: deque[float] = deque()

    def acquire(self) -> None:
        if not self.max_requests or not self.window_seconds:
            return
        now = time.monotonic()
        window_start = now - self.window_seconds
        while self._events and self._events[0] <= window_start:
            self._events.popleft()
        if len(self._events) >= self.max_requests:
            sleep_for = self.window_seconds - (now - self._events[0])
            if sleep_for > 0:
                time.sleep(min(sleep_for, self.window_seconds))
            self.acquire()
            return
        self._events.append(now)


def _extract_page_records(payload: Any) -> list[dict[str, Any]]:
    """Return a list of dict records from Gamma responses."""

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "markets", "items"):
            maybe = payload.get(key)
            if isinstance(maybe, list):
                return [item for item in maybe if isinstance(item, dict)]
    return []


def _extract_meta_total(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    if isinstance(meta, dict):
        total = meta.get("total")
        if isinstance(total, int):
            return total
        if isinstance(total, str) and total.isdigit():
            return int(total)
    return None


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


def _slugify(value: str | None) -> str | None:
    if not value:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or None


def _looks_like_range_token(token: str | None) -> bool:
    if not token:
        return False
    if re.search(r"\d", token):
        return True
    return token in {"over", "under", "gt", "lt", "gte", "lte", "above", "below"}


def _derive_group_slug(slug: str | None, question: str | None, group_item_title: str | None) -> str | None:
    if not group_item_title:
        return None
    base_slug = _slugify(slug) or _slugify(question)
    if not base_slug:
        return None
    if "committed-to-the-" in base_slug:
        _, remainder = base_slug.split("committed-to-the-", 1)
        base_slug = remainder or base_slug
    parts = base_slug.split("-")
    while parts and _looks_like_range_token(parts[-1]):
        parts.pop()
    trimmed = "-".join(parts).strip("-")
    return trimmed or base_slug


def _parse_group_threshold(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return None
    if isinstance(value, str):
        cleaned = value.strip().lower().replace(",", "").replace("$", "")
        cleaned = cleaned.lstrip("><= ")
        multiplier = 1.0
        if cleaned.endswith("k"):
            multiplier = 1_000.0
            cleaned = cleaned[:-1]
        elif cleaned.endswith("m"):
            multiplier = 1_000_000.0
            cleaned = cleaned[:-1]
        elif cleaned.endswith("b"):
            multiplier = 1_000_000_000.0
            cleaned = cleaned[:-1]
        match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        if not match:
            return None
        try:
            return float(match.group(0)) * multiplier
        except Exception:
            return None
    return None


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


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_liquidity(raw: dict[str, Any]) -> float | None:
    for key in (
        "liquidity_usd",
        "liquidityUsd",
        "liquidityUSD",
        "liquidity_clob",
        "liquidityNum",
        "liquidity_num",
        "liquidity",
    ):
        candidate = _coerce_float(raw.get(key))
        if candidate is not None:
            return candidate
    return None


def _extract_volume_24h(raw: dict[str, Any]) -> float | None:
    for key in ("volume24h", "volume_24h", "volume24hr", "volume24hrUsd", "volume24hUsd"):
        candidate = _coerce_float(raw.get(key))
        if candidate is not None:
            return candidate
    for key in ("volume_clob", "volumeClob", "volume1mo_clob"):
        candidate = _coerce_float(raw.get(key))
        if candidate is not None:
            return candidate
    for key in ("volume_num", "volumeNum", "volume"):
        candidate = _coerce_float(raw.get(key))
        if candidate is not None:
            return candidate
    return None


def _extract_orderbook_volume(raw: dict[str, Any]) -> float | None:
    for key in ("volume_clob", "volumeClob", "scaledCollateralVolume", "collateralVolume"):
        candidate = _coerce_float(raw.get(key))
        if candidate is not None:
            return candidate
    return None


def _extract_trades_quantity(raw: dict[str, Any]) -> int | None:
    for key in ("tradesQuantity", "trades_count", "tradesCount", "numberOfTrades"):
        candidate = _coerce_int(raw.get(key))
        if candidate is not None:
            return candidate
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


def _extract_clob_token_ids(raw: dict[str, Any]) -> list[str] | None:
    tokens = raw.get("tokens")
    if not isinstance(tokens, list):
        return None
    token_ids: list[str] = []
    for token in tokens:
        if not isinstance(token, dict):
            continue
        token_id = token.get("token_id") or token.get("tokenId")
        if token_id:
            token_ids.append(str(token_id))
    return token_ids or None


def _extract_clob_prices(raw: dict[str, Any]) -> list[float] | None:
    tokens = raw.get("tokens")
    if not isinstance(tokens, list):
        return None
    prices: list[float] = []
    for token in tokens:
        if not isinstance(token, dict):
            continue
        price = _coerce_float(token.get("price"))
        if price is not None:
            prices.append(price)
    return prices or None


def _extract_clob_outcomes(raw: dict[str, Any]) -> list[str] | None:
    tokens = raw.get("tokens")
    if not isinstance(tokens, list):
        return None
    outcomes: list[str] = []
    for token in tokens:
        if not isinstance(token, dict):
            continue
        outcome = _clean_string(token.get("outcome"))
        if outcome:
            outcomes.append(outcome)
    return outcomes or None


def _index_markets_by_identifier(markets: list[MarketPayload]) -> tuple[dict[str, MarketPayload], ...]:
    by_condition: dict[str, MarketPayload] = {}
    by_slug: dict[str, MarketPayload] = {}
    by_event: dict[str, MarketPayload] = {}
    for market in markets:
        if market.condition_id:
            by_condition[str(market.condition_id).lower()] = market
        if market.slug:
            by_slug[str(market.slug).lower()] = market
        if market.event_id:
            by_event[str(market.event_id).lower()] = market
    return by_condition, by_slug, by_event


def _build_market_hash_payload(market: MarketPayload) -> dict[str, Any]:
    return {
        "event_id": market.event_id,
        "title": market.title,
        "slug": market.slug,
        "category": market.category,
        "status": market.status,
        "outcomes": market.outcomes,
        "outcome_prices": market.outcome_prices,
        "tags": market.tags,
        "closed": market.closed,
        "image_url": market.image_url,
        "uma_resolution_status": market.uma_resolution_status,
        "condition_id": market.condition_id,
        "question_id": market.question_id,
        "closes_at": market.closes_at.isoformat() if isinstance(market.closes_at, datetime) else market.closes_at,
        "starts_at": market.starts_at.isoformat() if isinstance(market.starts_at, datetime) else market.starts_at,
        "orders_opened_at": (
            market.orders_opened_at.isoformat()
            if isinstance(market.orders_opened_at, datetime)
            else market.orders_opened_at
        ),
        "resolution_source": market.resolution_source,
        "market_maker": market.market_maker,
        "order_min_size": market.order_min_size,
        "price_tick_size": market.price_tick_size,
        "enable_order_book": market.enable_order_book,
        "clob_token_ids": market.clob_token_ids,
        "image_variants": market.image_variants,
        "liquidity_usd": market.liquidity_usd,
        "volume_24h_usd": market.volume_24h_usd,
        "orderbook_volume_usd": market.orderbook_volume_usd,
        "trades_quantity": market.trades_quantity,
        "group_slug": market.group_slug,
        "group_position": market.group_position,
        "group_item_title": market.group_item_title,
        "group_item_threshold": market.group_item_threshold,
        "best_bid": market.best_bid,
        "best_ask": market.best_ask,
        "spread": market.spread,
        "open_interest": market.open_interest,
        "volume": market.volume,
    }


def _match_clob_market(raw: dict[str, Any], indexes: tuple[dict[str, MarketPayload], ...]) -> MarketPayload | None:
    by_condition, by_slug, by_event = indexes
    condition_id = _clean_string(raw.get("condition_id") or raw.get("conditionId"))
    if condition_id:
        candidate = by_condition.get(condition_id.lower())
        if candidate:
            return candidate
    slug = _clean_string(raw.get("market_slug") or raw.get("marketSlug") or raw.get("slug"))
    if slug:
        candidate = by_slug.get(slug.lower())
        if candidate:
            return candidate
    raw_id = _clean_string(raw.get("id"))
    if raw_id:
        return by_event.get(raw_id.lower())
    return None


def _apply_clob_overlay(target: MarketPayload, raw: dict[str, Any]) -> None:
    token_ids = _extract_clob_token_ids(raw) or _extract_clob_ids(raw.get("clobTokenIds") or raw.get("clob_token_ids"))
    if token_ids:
        target.clob_token_ids = token_ids
    prices = _extract_clob_prices(raw)
    if prices and not target.outcome_prices:
        target.outcome_prices = prices
    outcomes = _extract_clob_outcomes(raw)
    if outcomes and not target.outcomes:
        target.outcomes = outcomes
    min_size = _coerce_float(raw.get("minimum_order_size"))
    if min_size is not None:
        target.order_min_size = min_size
    tick_size = _coerce_float(raw.get("minimum_tick_size"))
    if tick_size is not None:
        target.price_tick_size = tick_size
    order_book_enabled = raw.get("enable_order_book")
    if isinstance(order_book_enabled, bool):
        target.enable_order_book = order_book_enabled
    closes_at = _extract_timestamp_candidate(raw.get("end_date_iso") or raw.get("endDate") or raw.get("end_date"))
    if closes_at and target.closes_at is None:
        target.closes_at = closes_at
    # No extra_data mutation; normalized fields only


def merge_clob_markets(
    markets: list[MarketPayload],
    clob_client: ClobClient,
    *,
    max_pages: int | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Enrich existing market payloads with data from the CLOB API."""
    if not markets:
        return
    try:
        clob_markets = fetch_clob_markets(clob_client, max_pages=max_pages)
    except Exception as exc:  # pragma: no cover - defensive fetch guard
        if logger:
            logger.warning(
                "Failed to fetch clob markets",
                extra={"event": "clob.fetch.failed", "error": str(exc)},
            )
        return
    if not clob_markets:
        return
    indexes = _index_markets_by_identifier(markets)
    for raw in clob_markets:
        if not isinstance(raw, dict):
            continue
        target = _match_clob_market(raw, indexes)
        if target is None:
            continue
        _apply_clob_overlay(target, raw)


def fetch_clob_markets(clob_client: ClobClient, *, max_pages: int | None = None) -> list[dict[str, Any]]:
    """Page through the CLOB simplified markets endpoint."""
    results: list[dict[str, Any]] = []
    cursor: str | None = "MA=="
    pages = 0
    while True:
        payload = clob_client.get_simplified_markets(next_cursor=cursor)
        markets = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(markets, list):
            results.extend([m for m in markets if isinstance(m, dict)])
        cursor = payload.get("next_cursor") if isinstance(payload, dict) else None
        pages += 1
        if cursor is None or cursor == END_CURSOR or (max_pages and pages >= max_pages):
            break
    return results


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
