from __future__ import annotations

from app.config import Settings


def test_settings_defaults():
    cfg = Settings()
    assert cfg.clob_ws_url.startswith("wss://")
    assert cfg.fx_fallback_price == 0.0
    assert cfg.total_monetization == cfg.worsen_percent + cfg.haircut_percent + cfg.rake_percent


def test_cors_origins_resolved_adds_defaults():
    cfg = Settings(cors_allow_origins=["http://localhost:3000"])
    assert cfg.cors_allow_origins_resolved == ["http://localhost:3000"]


def test_cors_origins_resolved_respects_wildcard():
    cfg = Settings(cors_allow_origins=["*"])
    assert cfg.cors_allow_origins_resolved == ["*"]
