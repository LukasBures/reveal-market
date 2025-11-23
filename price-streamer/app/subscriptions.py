from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass
class SubscriptionManager:
    """Tracks active subscriptions and builds RTDS/CLOB subscribe/unsubscribe payloads."""

    max_items: int
    assets: set[str] = field(default_factory=set)
    topics: set[tuple[str, str, str | None]] = field(default_factory=set)  # (topic, type, filters)

    def add_assets(self, asset_ids: Iterable[str]) -> None:
        for asset_id in asset_ids:
            if len(self.assets) >= self.max_items:
                break
            self.assets.add(str(asset_id))

    def remove_asset(self, asset_id: str) -> None:
        self.assets.discard(str(asset_id))

    def build_clob_subscribe(self) -> str:
        return json.dumps({"assets_ids": sorted(self.assets), "type": "MARKET"})

    def build_rtds_subscribe(self) -> str:
        subs = [
            {"topic": topic, "type": type_, "filters": filters or ""} for topic, type_, filters in sorted(self.topics)
        ]
        return json.dumps({"action": "subscribe", "subscriptions": subs})

    def add_rtds_topic(self, topic: str, type_: str, filters: str | None = None) -> None:
        if len(self.topics) >= self.max_items:
            return
        self.topics.add((topic, type_, filters))
