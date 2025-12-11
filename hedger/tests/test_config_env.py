import importlib

from hedger.app import config as cfg


def test_database_url_prefers_rm(monkeypatch):
    monkeypatch.setenv("RM_DATABASE_URL", "postgresql+psycopg2://rm_user:<REDACTED>@db/rm")
    importlib.reload(cfg)
    settings = cfg.get_settings()
    assert settings.database_url == "postgresql+psycopg2://rm_user:<REDACTED>@db/rm"
