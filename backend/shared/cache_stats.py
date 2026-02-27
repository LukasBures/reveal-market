from __future__ import annotations


class CacheStats:
    """Best-effort cache hit/miss/error counters."""

    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0
        self.errors = 0

    def record_hit(self) -> None:
        self.hits += 1

    def record_miss(self) -> None:
        self.misses += 1

    def record_error(self) -> None:
        self.errors += 1

    def snapshot(self) -> dict[str, int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "errors": self.errors,
        }
