"""Helpers for interacting with the Polymarket Gamma API."""

from __future__ import annotations


def build_polymarket_markets_url(base_url: str) -> str:
    """Return a markets endpoint derived from the configured Polymarket base URL.

    The worker historically expected `RM_POLYMARKET_API_BASE` to be just the host
    (e.g. ``https://gamma-api.polymarket.com``) and appended ``/markets`` itself.
    Operators configuring a Polygon-specific feed often pointed the setting at a
    path that already ends with ``/markets`` (or includes query parameters), which
    meant requests were incorrectly sent to ``.../markets/markets`` and the feed
    returned 404. Normalising the URL here keeps both variants working without
    forcing everyone to renumber their env files.
    """

    normalized = (base_url or "").strip()
    if not normalized:
        raise ValueError("Polymarket base URL is required")

    if "?" in normalized:
        path, query = normalized.split("?", 1)
        query_suffix = f"?{query}"
    else:
        path = normalized
        query_suffix = ""

    trimmed = path.rstrip("/")
    if trimmed.lower().endswith("/markets"):
        return f"{trimmed}{query_suffix}"
    return f"{trimmed}/markets{query_suffix}"


__all__ = ["build_polymarket_markets_url"]
