from __future__ import annotations

import re

MARKETS_LIST_PREFIX = "markets:list"
CATEGORY_PREFIX = "markets:category"
SUGGEST_PREFIX = "markets:suggest"
RESOLUTION_PREFIX = "markets:resolution"
PROOF_PREFIX = "proofs:receipt"


def markets_list_cache_key(
    status: str | None,
    category: str | None,
    oracle: str | None,
    search: str | None,
    limit: int,
    offset: int,
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
    return f"{MARKETS_LIST_PREFIX}:" + "|".join(parts)


def category_cache_key(category: str, limit: int) -> str:
    slug = _slugify(category)
    return f"{CATEGORY_PREFIX}:{slug}|limit={limit}"


def suggest_cache_key(query: str, limit: int) -> str:
    normalized = (query or "*").strip().lower() or "*"
    return f"{SUGGEST_PREFIX}:{normalized}|limit={limit}"


def resolution_cache_key(condition_id: str) -> str:
    normalized = (condition_id or "*").strip().lower() or "*"
    return f"{RESOLUTION_PREFIX}:{normalized}"


def proof_receipt_cache_key(condition_id: str) -> str:
    normalized = (condition_id or "*").strip().lower() or "*"
    return f"{PROOF_PREFIX}:{normalized}"


def _slugify(value: str | None) -> str:
    if not value:
        return "*"
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "*"
