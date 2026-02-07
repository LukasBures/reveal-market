"""Adaptive load shedding for the API service.

This module tracks dependency failures and selectively sheds non-critical
traffic when the system is unhealthy. It is intentionally conservative and
only activates when thresholds are exceeded.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class LoadSheddingState:
    db_failures: int = 0
    cache_failures: int = 0
    last_shed_at: float = 0.0

    def record_db_failure(self) -> None:
        self.db_failures += 1

    def record_db_success(self) -> None:
        self.db_failures = 0

    def record_cache_failure(self) -> None:
        self.cache_failures += 1

    def record_cache_success(self) -> None:
        self.cache_failures = 0

    def should_shed(self, *, db_threshold: int, cache_threshold: int) -> bool:
        return self.db_failures >= db_threshold or self.cache_failures >= cache_threshold

    def mark_shed(self) -> None:
        self.last_shed_at = time.time()

    def in_cooldown(self, cooldown_seconds: int) -> bool:
        if cooldown_seconds <= 0:
            return False
        return time.time() < self.last_shed_at + cooldown_seconds

