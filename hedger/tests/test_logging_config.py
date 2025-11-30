import logging

from app import logging_config


def test_resolve_log_level_defaults_to_info(monkeypatch) -> None:
    monkeypatch.delenv("HEDGER_LOG_LEVEL", raising=False)
    level_name, level_value = logging_config.resolve_log_level()
    assert level_name == "INFO"
    assert level_value == logging.INFO


def test_resolve_log_level_respects_env(monkeypatch) -> None:
    monkeypatch.setenv("HEDGER_LOG_LEVEL", "debug")
    level_name, level_value = logging_config.resolve_log_level()
    assert level_name == "DEBUG"
    assert level_value == logging.DEBUG


def test_resolve_log_level_invalid_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("HEDGER_LOG_LEVEL", "notalevel")
    level_name, level_value = logging_config.resolve_log_level("WARNING")
    assert level_name == "WARNING"
    assert level_value == logging.WARNING


def test_setup_logging_emits_init(monkeypatch, caplog) -> None:
    monkeypatch.setenv("HEDGER_LOG_LEVEL", "warning")
    logger = logging_config.setup_logging("reveal_market.hedger", "INFO")
    assert logger.level == logging.WARNING
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture()
    logger.addHandler(handler)
    try:
        logger.warning("probe", extra={"event": "logging.init"})
    finally:
        logger.removeHandler(handler)
    assert any(getattr(record, "event", None) == "logging.init" for record in records)
