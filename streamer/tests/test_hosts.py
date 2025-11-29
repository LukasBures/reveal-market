from __future__ import annotations

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


def test_cors_prod_overrides_wildcard(monkeypatch):
    monkeypatch.setenv("MODE", "prod")
    from app import main

    monkeypatch.setattr(
        main,
        "PRESETS",
        {
            "prod": {
                "api_cors_origins": ["*"],
                "streamer_public": "https://stream.revealmarket.xyz",
                "streamer_internal": "https://stream.revealmarket.xyz",
            }
        },
    )
    monkeypatch.setattr(
        "app.main.get_settings",
        lambda: Settings(
            environment="prod", cors_allow_origins=["*"], public_base_url="https://stream.revealmarket.xyz"
        ),
    )
    app = main.create_app()
    assert "*" not in app.state.cors_origins
