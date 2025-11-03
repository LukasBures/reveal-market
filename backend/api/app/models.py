"""Thin wrapper around shared models to preserve historical import paths."""

from shared.models import Base, Market, MarketStatusEnum

__all__ = ["Base", "Market", "MarketStatusEnum"]
