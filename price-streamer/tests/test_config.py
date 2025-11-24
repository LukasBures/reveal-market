from __future__ import annotations

from app.config import Settings


def test_settings_defaults():
    cfg = Settings()
    assert cfg.clob_ws_url.startswith("wss://")
    assert str(cfg.clob_rest_markets_url).startswith("https://")
    assert cfg.fx_fallback_price == 0.0
    assert cfg.total_monetisation == cfg.worsen_percent + cfg.haircut_percent + cfg.rake_percent
