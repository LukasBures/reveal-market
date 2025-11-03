"""Utilities for retrieving and normalising market data from the Polymarket API."""

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
    category: Optional[str] = None
    metadata_uri: Optional[str] = None
    oracle: str = Field(default="polymarket")
    factory: Optional[str] = None
    market_address: Optional[str] = None
    status: str = Field(default="commit")
    outcomes: Any = None
    extra_data: Optional[Dict[str, Any]] = None

    @classmethod
    def from_strapi(cls, raw: Dict[str, Any]) -> "MarketPayload":
        """Normalise a Strapi market document into `MarketPayload`."""
        attributes = raw.get("attributes") or {}

        event_id = attributes.get("eventId") or raw.get("id")
        if event_id is None:
            raise ValueError("Polymarket record is missing an event identifier")

        title = (
            attributes.get("title")
            or attributes.get("question")
            or attributes.get("slug")
            or f"Market {event_id}"
        )
        title = str(title)

        category = _extract_category(attributes)
        metadata_uri_raw = (
            attributes.get("metadataUri")
            or attributes.get("metadata_uri")
            or attributes.get("metadata_url")
            or attributes.get("questionID")
        )
        oracle = attributes.get("oracle") or "polymarket"
        factory_raw = attributes.get("factory") or attributes.get("marketFactoryAddress")
        market_address_raw = (
            attributes.get("marketAddress")
            or attributes.get("marketMakerAddress")
            or attributes.get("conditionId")
        )
        status = attributes.get("status") or "commit"
        outcomes = attributes.get("outcomes") or attributes.get("prices")

        metadata_uri = str(metadata_uri_raw) if metadata_uri_raw is not None else None
        factory = str(factory_raw) if factory_raw is not None else None
        market_address = str(market_address_raw) if market_address_raw is not None else None

        extra_data = attributes if isinstance(attributes, dict) else None

        return cls(
            event_id=str(event_id),
            title=title,
            category=category,
            metadata_uri=metadata_uri,
            oracle=str(oracle),
            factory=factory,
            market_address=market_address,
            status=str(status),
            outcomes=outcomes,
            extra_data=extra_data,
        )


class PolymarketClient:
    """Lightweight client for the Polymarket Strapi API."""

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
        extra_params: Dict[str, Any] | None = None,
    ) -> List[MarketPayload]:
        """Walk the paginated API, returning a list of validated markets."""
        markets: List[MarketPayload] = []
        page = 1

        with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
            while True:
                params: Dict[str, Any] = {
                    "pagination[page]": page,
                    "pagination[pageSize]": page_size,
                    "sort": "updatedAt:desc",
                    "populate": "deep",
                }
                if extra_params:
                    params.update(extra_params)

                try:
                    response = client.get(self.base_url, params=params)
                    response.raise_for_status()
                    payload = response.json()
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.error("failed to fetch polymarket page %s: %s", page, exc)
                    break

                raw_markets = payload.get("data")
                if not isinstance(raw_markets, list) or not raw_markets:
                    break

                for raw in raw_markets:
                    if not isinstance(raw, dict):
                        continue
                    try:
                        markets.append(MarketPayload.from_strapi(raw))
                    except (ValidationError, ValueError) as exc:
                        logger.warning("skipping polymarket record: %s", exc)

                pagination = _extract_pagination(payload)
                page += 1

                if max_pages is not None and page > max_pages:
                    break
                if pagination is not None and page > pagination:
                    break

        return markets


def _extract_category(attributes: Dict[str, Any]) -> Optional[str]:
    """Try to infer a category/collection slug from the nested Strapi payload."""
    category = attributes.get("category")
    if isinstance(category, str):
        return category

    collections = attributes.get("collections")
    if isinstance(collections, dict):
        collection_data = collections.get("data")
        if isinstance(collection_data, list):
            for entry in collection_data:
                if not isinstance(entry, dict):
                    continue
                entry_attrs = entry.get("attributes") or {}
                if isinstance(entry_attrs, dict):
                    slug = entry_attrs.get("slug")
                    if isinstance(slug, str):
                        return slug
                    name = entry_attrs.get("name")
                    if isinstance(name, str):
                        return name
    return None


def _extract_pagination(payload: Dict[str, Any]) -> Optional[int]:
    """Return the total page count from Strapi metadata (if present)."""
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    pagination = meta.get("pagination")
    if not isinstance(pagination, dict):
        return None
    page_count = pagination.get("pageCount")
    if isinstance(page_count, int):
        return page_count
    return None
