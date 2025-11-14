import logging

from app import logging_config
from shared.logging import StructuredFormatter, reset_request_id, set_request_id


def test_request_context_filter_attaches_request_and_service() -> None:
    token = set_request_id("req-123")
    try:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="hello",
            args=(),
            exc_info=None,
        )
        filt = logging_config.RequestContextFilter("reveal_market.api")
        assert filt.filter(record) is True
        assert record.request_id == "req-123"
        assert record.service_name == "reveal_market.api"
    finally:
        reset_request_id(token)


def test_structured_formatter_shape() -> None:
    formatter = StructuredFormatter("reveal_market.api")
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=20,
        msg="event happened",
        args=(),
        exc_info=None,
    )
    record.event = "test.event"
    record.service_name = "reveal_market.api"
    output = formatter.format(record)
    assert "reveal_market.api" in output
    assert "test.event" in output
    assert "| INFO |" in output.upper()
