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


def _ip_in_networks(
    ip_value: ipaddress.IPv4Address | ipaddress.IPv6Address,
    networks: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    return any(ip_value in network for network in networks)


def resolve_client_ip(
    request: Request,
    trust_x_forwarded_for: bool,
    trusted_proxy_cidrs: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network] | None = None,
) -> str | None:
    client = request.client
    if client is None:
        return None
    direct_ip = client.host
    if not trust_x_forwarded_for:
        return direct_ip
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return direct_ip
    trusted_proxies = list(trusted_proxy_cidrs or [])
    try:
        direct_ip_obj = ipaddress.ip_address(direct_ip)
    except ValueError:
        return direct_ip
    if not trusted_proxies or not _ip_in_networks(direct_ip_obj, trusted_proxies):
        # Refuse spoofable forwarded headers from unknown peers.
        return direct_ip
    chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    chain.append(direct_ip)
    parsed_chain: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for candidate in chain:
        try:
            parsed_chain.append(ipaddress.ip_address(candidate))
        except ValueError:
            return direct_ip
    index = len(parsed_chain) - 1
    while index > 0 and _ip_in_networks(parsed_chain[index], trusted_proxies):
        index -= 1
    return str(parsed_chain[index])


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
