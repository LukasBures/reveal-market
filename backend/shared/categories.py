"""Canonical category metadata shared between the API and worker."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryDefinition:
    """Represents a canonical category and its alias/keyword metadata."""

    slug: str
    label: str
    aliases: Sequence[str] = ()
    keywords: Sequence[str] = ()


_CATEGORY_DEFINITIONS: tuple[CategoryDefinition, ...] = (
    CategoryDefinition(slug="trending", label="Trending"),
    CategoryDefinition(
        slug="politics",
        label="Politics",
        aliases=(
            "politic",
            "political",
            "us-politics",
            "world-politics",
            "governance",
            "government",
            "election",
            "elections",
        ),
        keywords=(
            "politic",
            "election",
            "primary",
            "vote",
            "ballot",
            "governor",
            "senate",
            "congress",
            "parliament",
            "minister",
            "mayor",
            "referendum",
            "caucus",
            "campaign",
        ),
    ),
    CategoryDefinition(
        slug="sports",
        label="Sports",
        aliases=(
            "sport",
            "sportsbook",
            "athletics",
            "nfl",
            "nba",
            "mlb",
            "nhl",
            "fifa",
            "ufc",
            "mma",
            "ncaa",
            "cfb",
            "f1",
        ),
        keywords=(
            "sport",
            "nfl",
            "nba",
            "mlb",
            "nhl",
            "ncaa",
            "cfb",
            "ufc",
            "mma",
            "soccer",
            "football",
            "basketball",
            "baseball",
            "tennis",
            "golf",
            "f1",
            "formula",
            "nascar",
            "cricket",
            "rugby",
            "olympic",
        ),
    ),
    CategoryDefinition(
        slug="finance",
        label="Finance",
        aliases=("equities", "stocks"),
        keywords=(
            "finance",
            "stock",
            "equity",
            "equities",
            "bond",
            "treasury",
            "market",
            "markets",
            "earnings",
            "stocks",
        ),
    ),
    CategoryDefinition(
        slug="economy",
        label="Economy",
        aliases=("macro", "macroeconomics"),
        keywords=(
            "economy",
            "macro",
            "inflation",
            "cpi",
            "ppi",
            "gdp",
            "jobs",
            "employment",
            "labor",
            "fed",
            "interest",
            "rate",
            "rates",
            "recession",
        ),
    ),
    CategoryDefinition(
        slug="crypto",
        label="Crypto",
        aliases=("digital-assets", "defi", "web3", "blockchain", "bitcoin", "ethereum"),
        keywords=(
            "crypto",
            "bitcoin",
            "btc",
            "ethereum",
            "eth",
            "token",
            "tokens",
            "defi",
            "web3",
            "blockchain",
            "nft",
            "solana",
            "polygon",
            "binance",
            "coin",
            "airdrop",
            "staking",
        ),
    ),
    CategoryDefinition(
        slug="geopolitics",
        label="Geopolitics",
        aliases=("geo", "world-affairs", "global-conflict", "conflict"),
        keywords=(
            "geopolitic",
            "war",
            "conflict",
            "invasion",
            "israel",
            "palestine",
            "gaza",
            "ukraine",
            "russia",
            "china",
            "taiwan",
            "iran",
            "nato",
            "military",
            "missile",
            "army",
            "border",
        ),
    ),
    CategoryDefinition(
        slug="ai-tech",
        label="AI & Tech",
        aliases=("ai", "artificial-intelligence", "technology", "tech", "chips"),
        keywords=(
            "ai",
            "artificial",
            "tech",
            "technology",
            "chip",
            "chips",
            "semiconductor",
            "software",
            "hardware",
            "nvidia",
            "openai",
            "anthropic",
            "google",
            "microsoft",
            "meta",
            "apple",
            "robot",
        ),
    ),
)


def _slugify(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


CANONICAL_CATEGORIES: Mapping[str, str] = {entry.slug: entry.label for entry in _CATEGORY_DEFINITIONS}

_ALIAS_INDEX: dict[str, str] = {}
for entry in _CATEGORY_DEFINITIONS:
    for alias in entry.aliases:
        slug = _slugify(alias)
        if slug and slug not in CANONICAL_CATEGORIES:
            _ALIAS_INDEX[slug] = entry.slug

_KEYWORD_INDEX: dict[str, tuple[str, ...]] = {
    entry.slug: tuple(keyword for keyword in entry.keywords if keyword)
    for entry in _CATEGORY_DEFINITIONS
    if entry.keywords
}


def canonical_category_from_slug(value: str | None) -> tuple[str, str] | None:
    """Return a canonical category slug + label if the provided slug matches."""

    slug = _slugify(value)
    if not slug:
        return None
    canonical_slug = slug if slug in CANONICAL_CATEGORIES else _ALIAS_INDEX.get(slug)
    if canonical_slug is None:
        return None
    return canonical_slug, CANONICAL_CATEGORIES[canonical_slug]


def canonical_category_from_raw(raw: str | None, *, tags: Iterable[str] | None = None) -> tuple[str, str] | None:
    """Attempt to normalise an arbitrary category/tag string into our canonical set."""

    direct = canonical_category_from_slug(raw)
    if direct:
        return direct

    tag_slugs: list[str] = []
    for tag in tags or []:
        slug = _slugify(tag)
        if slug:
            tag_slugs.append(slug)
    for tag_slug in tag_slugs:
        if tag_slug in CANONICAL_CATEGORIES:
            return tag_slug, CANONICAL_CATEGORIES[tag_slug]
    for tag_slug in tag_slugs:
        alias_match = _ALIAS_INDEX.get(tag_slug)
        if alias_match:
            return alias_match, CANONICAL_CATEGORIES[alias_match]

    slug = _slugify(raw)
    keyword_match = _match_keywords(slug)
    if keyword_match:
        return keyword_match, CANONICAL_CATEGORIES[keyword_match]
    for tag_slug in tag_slugs:
        keyword_match = _match_keywords(tag_slug)
        if keyword_match:
            return keyword_match, CANONICAL_CATEGORIES[keyword_match]
    return None


def _match_keywords(slug: str) -> str | None:
    if not slug:
        return None
    for category_slug, keywords in _KEYWORD_INDEX.items():
        for keyword in keywords:
            if keyword and keyword in slug:
                return category_slug
    return None


_GEOPOLITICS_TITLE_KEYWORDS = frozenset(
    {
        "ukraine",
        "russia",
        "china",
        "taiwan",
        "iran",
        "gaza",
        "israel",
        "palestine",
        "nato",
        "military",
        "missile",
        "invasion",
        "conflict",
        "war",
        "army",
        "border",
        "geopolit",
        "sanction",
        "tariff",
        "trade-war",
    }
)


def refine_category(slug: str, title: str | None) -> tuple[str, str] | None:
    """Re-check a market initially categorised as *politics* for geopolitics signals in its title."""
    if slug != "politics" or not title:
        return None
    lowered = _slugify(title)
    for kw in _GEOPOLITICS_TITLE_KEYWORDS:
        if kw in lowered:
            return "geopolitics", CANONICAL_CATEGORIES["geopolitics"]
    return None
