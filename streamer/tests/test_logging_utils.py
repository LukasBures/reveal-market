import logging

from app import logging_utils


def test_resolve_log_level_defaults_to_info(monkeypatch) -> None:
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    level_name, level_value = logging_utils.resolve_log_level()
    assert level_name == "INFO"
    assert level_value == logging.INFO


def test_resolve_log_level_respects_env(monkeypatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "debug")
    level_name, level_value = logging_utils.resolve_log_level("WARNING")
    assert level_name == "DEBUG"
    assert level_value == logging.DEBUG


def test_resolve_log_level_invalid_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "notalevel")
    level_name, level_value = logging_utils.resolve_log_level("WARNING")
    assert level_name == "WARNING"
    assert level_value == logging.WARNING


def test_setup_logging_sets_service_level_and_logs(monkeypatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "warning")
    service_name = "reveal_market.streamer.test"
    logging_utils.setup_logging(service_name, "INFO")
    logger = logging.getLogger(service_name)
    assert logger.level == logging.WARNING
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture()
    logger.addHandler(handler)
    try:
        logger.warning("probe", extra={"event": "probe.event"})
    finally:
        logger.removeHandler(handler)
    assert any(getattr(record, "event", None) == "probe.event" for record in records)
