import logging

from app import logging_config
from shared.logging import reset_request_id, set_request_id


def test_request_context_filter_attaches_request_and_service() -> None:
    token = set_request_id("req-worker")
    try:
        record = logging.LogRecord(
            name="worker",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="processing",
            args=(),
            exc_info=None,
        )
        filt = logging_config.RequestContextFilter("reveal_market.worker")
        assert filt.filter(record) is True
        assert record.request_id == "req-worker"
        assert record.service_name == "reveal_market.worker"
    finally:
        reset_request_id(token)


def test_resolve_log_level_defaults_to_info(monkeypatch) -> None:
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    level_name, level = logging_config.resolve_log_level()
    assert level_name == "INFO"
    assert level == logging.INFO


def test_resolve_log_level_invalid_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "garbage")
    level_name, level = logging_config.resolve_log_level("DEBUG")
    assert level_name == "DEBUG"
    assert level == logging.DEBUG


def test_resolve_log_level_respects_valid_env(monkeypatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "warning")
    level_name, level = logging_config.resolve_log_level()
    assert level_name == "WARNING"
    assert level == logging.WARNING
