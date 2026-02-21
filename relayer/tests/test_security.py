from __future__ import annotations

import ipaddress
from types import SimpleNamespace

from relayer.security import resolve_client_ip


class _DummyRequest:
    def __init__(self, host: str, forwarded: str | None = None):
        self.client = SimpleNamespace(host=host)
        self.headers: dict[str, str] = {}
        if forwarded is not None:
            self.headers["x-forwarded-for"] = forwarded


def test_resolve_client_ip_ignores_xff_without_trusted_proxy():
    request = _DummyRequest("10.0.0.9", "198.51.100.1, 10.0.0.8")
    resolved = resolve_client_ip(request, trust_x_forwarded_for=True, trusted_proxy_cidrs=[])
    assert resolved == "10.0.0.9"


def test_resolve_client_ip_uses_rightmost_untrusted_hop():
    request = _DummyRequest("10.0.0.9", "198.51.100.1, 10.0.0.8")
    trusted = [ipaddress.ip_network("10.0.0.0/24")]
    resolved = resolve_client_ip(request, trust_x_forwarded_for=True, trusted_proxy_cidrs=trusted)
    assert resolved == "198.51.100.1"


def test_resolve_client_ip_falls_back_on_invalid_xff():
    request = _DummyRequest("10.0.0.9", "not-an-ip")
    trusted = [ipaddress.ip_network("10.0.0.0/24")]
    resolved = resolve_client_ip(request, trust_x_forwarded_for=True, trusted_proxy_cidrs=trusted)
    assert resolved == "10.0.0.9"
