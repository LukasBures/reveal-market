from __future__ import annotations

import asyncio
import socket
import warnings

import pytest


@pytest.fixture(autouse=True)
def block_network_calls(monkeypatch):
    """Relayer tests must stay offline; fail fast on real sockets."""

    allowed_hosts = {"127.0.0.1", "localhost", "::1"}
    real_create_connection = socket.create_connection

    def guarded_create_connection(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host in allowed_hosts:
            return real_create_connection(address, *args, **kwargs)
        raise RuntimeError(f"Network access to {host} is blocked during tests")

    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)


@pytest.fixture(autouse=True)
def _close_event_loop():
    """Close any leftover event loop between tests to avoid ResourceWarnings."""

    yield
    policy = asyncio.get_event_loop_policy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            loop = policy.get_event_loop()
        except RuntimeError:
            loop = getattr(getattr(policy, "_local", None), "_loop", None)
    if loop and not loop.is_closed():
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            policy.set_event_loop(None)
        except RuntimeError:
            pass
