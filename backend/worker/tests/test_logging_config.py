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
