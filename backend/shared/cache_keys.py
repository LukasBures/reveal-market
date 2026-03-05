from __future__ import annotations

import re

CACHE_VERSION = "v1"
MARKETS_LIST_PREFIX = f"{CACHE_VERSION}:markets:list"
CATEGORY_PREFIX = f"{CACHE_VERSION}:markets:category"
SUGGEST_PREFIX = f"{CACHE_VERSION}:markets:suggest"
RESOLUTION_PREFIX = f"{CACHE_VERSION}:markets:resolution"
PROOF_PREFIX = f"{CACHE_VERSION}:proofs:receipt"
GROUP_PREFIX = f"{CACHE_VERSION}:markets:group"
GROUP_MARKETS_PREFIX = f"{CACHE_VERSION}:markets:group:markets"
MARKET_STATS_PREFIX = f"{CACHE_VERSION}:market:stats"
CLOB_PRICES_HISTORY_PREFIX = f"{CACHE_VERSION}:clob:prices-history"
EVENTS_COUNT_PREFIX = f"{CACHE_VERSION}:events:count"


def _escape_pipe(value: str) -> str:
    """Escape pipe characters in cache key segments to prevent key collisions."""
    return value.replace("|", "%7C")


def markets_list_cache_key(
    status: str | None,
    category: str | None,
    oracle: str | None,
    search: str | None,
    limit: int,
    offset: int,
    order_by: str | None = None,
    trending: bool | None = None,
    featured: bool | None = None,
    coalesce_groups: bool | None = None,
    closes_within_hours: int | None = None,
) -> str:
    """Build the cache key used for /markets list responses."""

    normalized_search = _escape_pipe((search or "").strip().lower() or "*")
    parts = [
        f"status={_escape_pipe(status or '*')}",
        f"category={_escape_pipe(category or '*')}",
        f"oracle={_escape_pipe(oracle or '*')}",
        f"search={normalized_search}",
        f"limit={limit}",
        f"offset={offset}",
    ]
    if order_by:
        parts.append(f"order_by={_escape_pipe(order_by)}")
    if trending is not None:
        parts.append(f"trending={int(bool(trending))}")
    if featured is not None:
        parts.append(f"featured={int(bool(featured))}")
    if coalesce_groups is not None:
        parts.append(f"coalesce_groups={int(bool(coalesce_groups))}")
    if closes_within_hours is not None:
        parts.append(f"closes_within_hours={int(closes_within_hours)}")
    return f"{MARKETS_LIST_PREFIX}:" + "|".join(parts)


def category_cache_key(
    category: str, limit: int, offset: int = 0, order_by: str | None = None, coalesce_groups: bool | None = None
) -> str:
    slug = _slugify(category)
    parts = [f"{CATEGORY_PREFIX}:{slug}", f"limit={limit}", f"offset={offset}"]
    if order_by:
        parts.append(f"order_by={order_by}")
    if coalesce_groups is not None:
        parts.append(f"coalesce_groups={int(bool(coalesce_groups))}")
    return "|".join(parts)


def suggest_cache_key(query: str, limit: int) -> str:
    normalized = _escape_pipe((query or "*").strip().lower() or "*")
    return f"{SUGGEST_PREFIX}:{normalized}|limit={limit}"


def resolution_cache_key(condition_id: str) -> str:
    normalized = (condition_id or "*").strip().lower() or "*"
    return f"{RESOLUTION_PREFIX}:{normalized}"


def proof_receipt_cache_key(condition_id: str) -> str:
    normalized = (condition_id or "*").strip().lower() or "*"
    return f"{PROOF_PREFIX}:{normalized}"


def group_cache_key(group_slug: str) -> str:
    slug = _slugify(group_slug)
    return f"{GROUP_PREFIX}:{slug}"


def group_markets_cache_key(group_slug: str) -> str:
    slug = _slugify(group_slug)
    return f"{GROUP_MARKETS_PREFIX}:{slug}"


def market_stats_cache_key(event_id: str) -> str:
    normalized = (event_id or "*").strip() or "*"
    return f"{MARKET_STATS_PREFIX}:{normalized}"


def clob_prices_history_cache_key(
    token_id: str,
    interval: str | None,
    fidelity: int | None,
    start_ts: int | None,
    end_ts: int | None,
) -> str:
    """Build the cache key used for CLOB price history lookups."""

    normalized_token = (token_id or "*").strip() or "*"
    normalized_interval = (interval or "*").strip().lower() or "*"
    normalized_fidelity = str(fidelity) if fidelity is not None else "*"
    normalized_start = str(start_ts) if start_ts is not None else "*"
    normalized_end = str(end_ts) if end_ts is not None else "*"
    return (
        f"{CLOB_PRICES_HISTORY_PREFIX}:{normalized_token}:"
        f"{normalized_interval}:{normalized_fidelity}:{normalized_start}:{normalized_end}"
    )


def events_count_cache_key(
    status: str | None,
    category: str | None,
    oracle: str | None,
    search: str | None,
    featured: bool | None = None,
) -> str:
    normalized_search = _escape_pipe((search or "").strip().lower() or "*")
    parts = [
        f"status={_escape_pipe(status or '*')}",
        f"category={_escape_pipe(category or '*')}",
        f"oracle={_escape_pipe(oracle or '*')}",
        f"search={normalized_search}",
    ]
    if featured is not None:
        parts.append(f"featured={int(bool(featured))}")
    return f"{EVENTS_COUNT_PREFIX}:" + "|".join(parts)


def _slugify(value: str | None) -> str:
    if not value:
        return "*"
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "*"
