from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_defaults():
    cfg = Settings()
    assert cfg.clob_ws_url.startswith("wss://")
    assert cfg.fx_fallback_price == 3.0
    assert cfg.total_monetization == cfg.worsen_percent + cfg.haircut_percent + cfg.rake_percent


def test_cors_origins_resolved_adds_defaults():
    cfg = Settings(cors_allow_origins=["http://localhost:3000"])
    assert cfg.cors_allow_origins_resolved == ["http://localhost:3000"]


def test_cors_origins_resolved_respects_wildcard_in_non_prod():
    cfg = Settings(environment="local", cors_allow_origins=["*"])
    assert cfg.cors_allow_origins_resolved == ["*"]


def test_cors_wildcard_rejected_in_prod():
    with pytest.raises(ValidationError, match="Wildcard CORS"):
        Settings(environment="prod", cors_allow_origins=["*"])
