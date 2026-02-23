import logging

from app.config import Settings
from app.main import create_app


def test_config_log_scrubs_passphrase(monkeypatch, caplog) -> None:
    settings = Settings(
        environment="test",
        admin_internal_secret="internal-secret",  # noqa: S106 - test fixture
        polymarket_api_passphrase="super-secret",  # noqa: S106 - test fixture
    )

    class _DummyService:
        def __init__(self, _settings: Settings) -> None:
            self.settings = _settings

    def _fake_setup_logging(service_name: str, level: str = "INFO") -> logging.Logger:
        logger = logging.getLogger(service_name)
        logger.setLevel(logging.INFO)
        return logger

    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.main.setup_logging", _fake_setup_logging)
    monkeypatch.setattr("app.main.HedgerService", _DummyService)

    caplog.set_level(logging.INFO)
    create_app()

    records = [record for record in caplog.records if getattr(record, "event", None) == "service.config"]
    assert records, "expected service.config log"
    config = records[0].config
    assert "polymarket_api_passphrase" not in config
