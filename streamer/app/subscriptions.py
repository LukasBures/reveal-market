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
    version: int = 0

    def _bump_version(self) -> None:
        self.version += 1

    def add_assets(self, asset_ids: Iterable[str], *, bump: bool = True) -> bool:
        changed = False
        for asset_id in asset_ids:
            if len(self.assets) >= self.max_items:
                break
            asset = str(asset_id)
            if asset not in self.assets:
                self.assets.add(asset)
                changed = True
        if changed and bump:
            self._bump_version()
        return changed

    def replace_asset(self, old_asset: str, new_assets: Iterable[str]) -> None:
        """Swap a placeholder asset for concrete ids (e.g., clob token ids)."""

        changed = False
        if old_asset in self.assets:
            self.assets.discard(old_asset)
            changed = True
        added = self.add_assets(new_assets, bump=False)
        if changed or added:
            self._bump_version()

    def remove_asset(self, asset_id: str) -> None:
        asset = str(asset_id)
        if asset in self.assets:
            self.assets.discard(asset)
            self._bump_version()

    def build_clob_subscribe(self) -> str:
        return json.dumps({"assets_ids": sorted(self.assets), "type": "market"})

    def build_rtds_subscribe(self) -> str:
        subs = [
            {"topic": topic, "type": type_, "filters": filters or ""} for topic, type_, filters in sorted(self.topics)
        ]
        return json.dumps({"action": "subscribe", "subscriptions": subs})

    def add_rtds_topic(self, topic: str, type_: str, filters: str | None = None) -> bool:
        if len(self.topics) >= self.max_items:
            return False
        entry = (topic, type_, filters)
        if entry not in self.topics:
            self.topics.add(entry)
            self._bump_version()
            return True
        return False
