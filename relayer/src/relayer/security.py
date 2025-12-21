import asyncio
import ipaddress
import time
from collections import deque
from collections.abc import Sequence

from fastapi import Request

from .config import IPAllowEntry


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._lock = asyncio.Lock()
        self._buckets: dict[str, deque[float]] = {}

    async def allow(self, key: str) -> bool:
        now = time.monotonic()
        async with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = deque()
                self._buckets[key] = bucket
            while bucket and now - bucket[0] > self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                return False
            bucket.append(now)
            return True


def resolve_client_ip(request: Request, trust_x_forwarded_for: bool) -> str | None:
    if trust_x_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            candidate = forwarded.split(",")[0].strip()
            if candidate:
                return candidate
    client = request.client
    if client:
        return client.host
    return None


def ip_allowed(client_ip: str | None, allowlist: Sequence[IPAllowEntry]) -> bool:
    if not allowlist:
        return True
    if not client_ip:
        return False
    try:
        ip_obj = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for entry in allowlist:
        if isinstance(entry, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            if ip_obj == entry:
                return True
        else:
            if ip_obj in entry:
                return True
    return False
