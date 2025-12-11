from __future__ import annotations

import importlib
import socket
import sys

import pytest

REQUIRED_MODULES = ["pydantic", "httpx", "tenacity"]
missing = [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]

if missing:
    deps = ", ".join(missing)
    sys.stdout.write(
        f"\nSkipping hedger tests: missing dependencies {deps}. Run 'uv sync --project hedger --extra dev' first.\n"
    )
    raise SystemExit(0)


@pytest.fixture(autouse=True)
def block_network_calls(monkeypatch):
    """Ensure hedger tests never hit live services."""

    allowed_hosts = {"127.0.0.1", "localhost", "::1"}
    real_create_connection = socket.create_connection

    def guarded_create_connection(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host in allowed_hosts:
            return real_create_connection(address, *args, **kwargs)
        raise RuntimeError(f"Network access to {host} is blocked during tests")

    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
