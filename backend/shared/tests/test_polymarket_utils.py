from __future__ import annotations

import pytest

from shared.polymarket import build_polymarket_markets_url


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("https://gamma-api.polymarket.com", "https://gamma-api.polymarket.com/markets"),
        ("https://gamma-api.polymarket.com/", "https://gamma-api.polymarket.com/markets"),
        (
            "https://gamma-api.polymarket.com/polygon/markets",
            "https://gamma-api.polymarket.com/polygon/markets",
        ),
        (
            "https://gamma-api.polymarket.com/polygon/markets/",
            "https://gamma-api.polymarket.com/polygon/markets",
        ),
        (
            "https://gamma-api.polymarket.com/polygon?chain=137",
            "https://gamma-api.polymarket.com/polygon/markets?chain=137",
        ),
        (
            "https://gamma-api.polymarket.com/polygon/markets?chain=137",
            "https://gamma-api.polymarket.com/polygon/markets?chain=137",
        ),
    ],
)
def test_build_polymarket_markets_url_handles_variants(base: str, expected: str):
    assert build_polymarket_markets_url(base) == expected


def test_build_polymarket_markets_url_rejects_empty():
    with pytest.raises(ValueError):
        build_polymarket_markets_url("")
