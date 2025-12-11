from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def block_network_calls(monkeypatch):
    """Fail fast if a test tries to reach the network instead of using mocks."""

    allowed_hosts = {"127.0.0.1", "localhost", "::1"}
    real_create_connection = socket.create_connection

    def guarded_create_connection(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host in allowed_hosts:
            return real_create_connection(address, *args, **kwargs)
        raise RuntimeError(f"Network access to {host} is blocked during tests")

    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
