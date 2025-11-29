"""Shared domain models and utilities used by both the API and worker services."""

from importlib import import_module
from typing import Any

__all__ = ["cache", "categories", "logging", "metrics", "models", "onchain", "repository"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        return import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
