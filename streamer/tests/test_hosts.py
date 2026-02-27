from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.main import _compute_cors_host_warnings


def test_compute_host_warnings_env_mismatch():
    settings = Settings(public_base_url="https://stream.example.com", cors_allow_origins=["https://revealmarket.xyz"])
    warnings = _compute_cors_host_warnings(
        settings, settings.cors_allow_origins_resolved, env_streamer_url="https://other.example.com"
    )
    assert any(w.get("reason") == "env_mismatch" for w in warnings)


def test_compute_host_warnings_missing_cors_origin():
    settings = Settings(public_base_url="https://stream.example.com", cors_allow_origins=["https://revealmarket.xyz"])
    warnings = _compute_cors_host_warnings(settings, settings.cors_allow_origins_resolved, env_streamer_url=None)
    assert any(w.get("reason") == "public_not_in_cors" for w in warnings)


def test_cors_wildcard_rejected_at_config_level_in_prod():
    """Wildcard CORS is now rejected by the Pydantic validator (M13), not at create_app time."""
    with pytest.raises(ValidationError, match="Wildcard CORS"):
        Settings(environment="prod", cors_allow_origins=["*"], public_base_url="https://stream.revealmarket.xyz")
