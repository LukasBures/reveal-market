from __future__ import annotations

import re
from typing import Optional

MARKETS_LIST_PREFIX = "markets:list"
CATEGORY_PREFIX = "markets:category"
TAG_PREFIX = "markets:tag"
SUGGEST_PREFIX = "markets:suggest"
RESOLUTION_PREFIX = "markets:resolution"


def markets_list_cache_key(
    status: Optional[str],
    category: Optional[str],
    oracle: Optional[str],
    search: Optional[str],
    limit: int,
    offset: int,
) -> str:
    """Build the cache key used for /markets list responses."""

    parts = [
        f"status={status or '*'}",
        f"category={category or '*'}",
        f"oracle={oracle or '*'}",
        f"search={search or '*'}",
        f"limit={limit}",
        f"offset={offset}",
    ]
    return f"{MARKETS_LIST_PREFIX}:" + "|".join(parts)


def category_cache_key(category: str, limit: int) -> str:
    slug = _slugify(category)
    return f"{CATEGORY_PREFIX}:{slug}|limit={limit}"


def tag_cache_key(tag: str, limit: int) -> str:
    slug = _slugify(tag)
    return f"{TAG_PREFIX}:{slug}|limit={limit}"


def suggest_cache_key(query: str, limit: int) -> str:
    normalized = (query or "*").strip().lower() or "*"
    return f"{SUGGEST_PREFIX}:{normalized}|limit={limit}"


def resolution_cache_key(condition_id: str) -> str:
    normalized = (condition_id or "*").strip().lower() or "*"
    return f"{RESOLUTION_PREFIX}:{normalized}"


def _slugify(value: Optional[str]) -> str:
    if not value:
        return "*"
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "*"
