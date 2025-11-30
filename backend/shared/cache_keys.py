from __future__ import annotations

import re

CACHE_VERSION = "v1"
MARKETS_LIST_PREFIX = f"{CACHE_VERSION}:markets:list"
CATEGORY_PREFIX = f"{CACHE_VERSION}:markets:category"
SUGGEST_PREFIX = f"{CACHE_VERSION}:markets:suggest"
RESOLUTION_PREFIX = f"{CACHE_VERSION}:markets:resolution"
PROOF_PREFIX = f"{CACHE_VERSION}:proofs:receipt"
GROUP_PREFIX = f"{CACHE_VERSION}:markets:group"


def markets_list_cache_key(
    status: str | None,
    category: str | None,
    oracle: str | None,
    search: str | None,
    limit: int,
    offset: int,
    order_by: str | None = None,
    trending: bool | None = None,
) -> str:
    """Build the cache key used for /markets list responses."""

    normalized_search = (search or "").strip().lower() or "*"
    parts = [
        f"status={status or '*'}",
        f"category={category or '*'}",
        f"oracle={oracle or '*'}",
        f"search={normalized_search}",
        f"limit={limit}",
        f"offset={offset}",
    ]
    if order_by:
        parts.append(f"order_by={order_by}")
    if trending is not None:
        parts.append(f"trending={int(bool(trending))}")
    return f"{MARKETS_LIST_PREFIX}:" + "|".join(parts)


def category_cache_key(category: str, limit: int, offset: int = 0) -> str:
    slug = _slugify(category)
    return f"{CATEGORY_PREFIX}:{slug}|limit={limit}|offset={offset}"


def suggest_cache_key(query: str, limit: int) -> str:
    normalized = (query or "*").strip().lower() or "*"
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


def _slugify(value: str | None) -> str:
    if not value:
        return "*"
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "*"
