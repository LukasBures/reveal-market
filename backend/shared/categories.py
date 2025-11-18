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
    CategoryDefinition(slug="breaking", label="Breaking"),
    CategoryDefinition(slug="new", label="New"),
    CategoryDefinition(slug="politics", label="Politics"),
    CategoryDefinition(slug="sports", label="Sports"),
    CategoryDefinition(slug="finance", label="Finance"),
    CategoryDefinition(slug="crypto", label="Crypto"),
    CategoryDefinition(slug="geopolitics", label="Geopolitics"),
    CategoryDefinition(slug="earnings", label="Earnings"),
    CategoryDefinition(slug="tech", label="Tech"),
    CategoryDefinition(slug="culture", label="Culture"),
    CategoryDefinition(slug="world", label="World"),
    CategoryDefinition(slug="economy", label="Economy"),
    CategoryDefinition(slug="elections", label="Elections"),
    CategoryDefinition(slug="mentions", label="Mentions"),
)


def _slugify(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
