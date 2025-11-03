"""Utilities for retrieving and normalising market data from the Polymarket APIs."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("reveal_market.worker.polymarket")


class MarketPayload(BaseModel):
    """Internal representation of a Polymarket market the worker can persist."""

    event_id: str
    title: str
    slug: Optional[str] = None
    category: Optional[str] = None
    metadata_uri: Optional[str] = None
    oracle: str = Field(default="polymarket")
    factory: Optional[str] = None
    market_address: Optional[str] = None
    status: str = Field(default="commit")
    outcomes: Optional[List[str]] = None
    outcome_prices: Optional[List[float]] = None
    extra_data: Optional[Dict[str, Any]] = None
    rake_bps: Optional[int] = None
    condition_id: Optional[str] = None
    question_id: Optional[str] = None
    image_url: Optional[str] = None
    closed: Optional[bool] = None
    uma_resolution_status: Optional[str] = None

    @classmethod
    def from_gamma(cls, raw: Dict[str, Any]) -> "MarketPayload":
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
        uma_status = raw.get("umaResolutionStatus") or raw.get("polymarketEventStatus")

        outcomes = _extract_outcomes(raw.get("outcomes"))
        outcome_prices = _extract_prices(raw.get("outcomePrices"))
        category = _derive_category(raw)
        status = _derive_status(closed, uma_status)

        extra_data: Dict[str, Any] = {"gamma": raw}

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
            outcomes=outcomes,
            outcome_prices=outcome_prices,
            extra_data=extra_data,
            rake_bps=None,
            condition_id=str(condition_id) if condition_id is not None else None,
            question_id=str(question_id) if question_id is not None else None,
            image_url=str(image_url) if image_url is not None else None,
            closed=bool(closed) if isinstance(closed, bool) else None,
            uma_resolution_status=str(uma_status) if uma_status is not None else None,
        )


class PolymarketClient:
    """Lightweight client for the Polymarket Gamma REST API."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.timeout = timeout
        self._transport = transport

    def fetch_markets(
        self,
        *,
        page_size: int = 100,
        max_pages: int | None = None,
        order: str = "id",
        ascending: bool = False,
        closed: Optional[bool] = None,
        extra_params: Dict[str, Any] | None = None,
    ) -> List[MarketPayload]:
        """Walk the offset-based API, returning a list of validated markets."""
        markets: List[MarketPayload] = []
        offset = 0
        page = 0

        with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
            while True:
                params: Dict[str, Any] = {
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
                try:
                    response = client.get(url, params=params)
                    response.raise_for_status()
                    payload = response.json()
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.error("failed to fetch polymarket page offset=%s: %s", offset, exc)
                    break

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


def _extract_outcomes(outcomes: Any) -> Optional[List[str]]:
    if not isinstance(outcomes, list):
        return None
    cleaned: List[str] = []
    for item in outcomes:
        if isinstance(item, str):
            cleaned.append(item)
        elif isinstance(item, dict):
            label = item.get("name") or item.get("outcome") or item.get("label")
            if label is not None:
                cleaned.append(str(label))
    return cleaned or None


def _extract_prices(prices: Any) -> Optional[List[float]]:
    if not isinstance(prices, list):
        return None
    cleaned: List[float] = []
    for value in prices:
        if isinstance(value, (int, float)):
            cleaned.append(float(value))
        elif isinstance(value, str):
            try:
                cleaned.append(float(value))
            except ValueError:
                continue
    return cleaned or None


def _derive_category(raw: Dict[str, Any]) -> Optional[str]:
    tags = raw.get("tags")
    if isinstance(tags, list):
        for entry in tags:
            if isinstance(entry, str) and entry:
                return entry
            if isinstance(entry, dict):
                candidate = entry.get("slug") or entry.get("name")
                if isinstance(candidate, str) and candidate:
                    return candidate
    category = raw.get("category")
    if isinstance(category, str) and category:
        return category
    return None


def _derive_status(closed: Any, resolution_status: Any) -> str:
    if isinstance(resolution_status, str):
        lowered = resolution_status.lower()
        if lowered in {"resolved", "settled", "confirmed", "resolved_final"}:
            return "settled"
    if isinstance(closed, bool) and closed:
        return "locked"
    return "commit"
