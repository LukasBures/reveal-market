from __future__ import annotations

import json
import logging
import time

from shared import logging as shared_logging


def test_log_event_embeds_event_and_custom_fields(caplog):
    logger = logging.getLogger("shared.logging.test")
    with caplog.at_level(logging.INFO):
        shared_logging.log_event(
            logger,
            logging.INFO,
            event="unit.test",
            message="structured message",
            correlation_id="abc123",
            attempt=2,
        )
    assert any(record.event == "unit.test" for record in caplog.records)
    record = caplog.records[0]
    assert record.correlation_id == "abc123"
    assert record.attempt == 2
    assert "structured message" in record.getMessage()


def test_structured_formatter_serializes_payload_with_request_id():
    formatter = shared_logging.StructuredFormatter("reveal-market")
    record = logging.LogRecord(
        name="reveal_market.api",
        level=logging.WARNING,
        pathname=__file__,
        lineno=42,
        msg="format me",
        args=(),
        exc_info=None,
    )
    record.event = "unit.formatter"
    record.request_id = "req-789"
    record.extra_field = "value"
    line = formatter.format(record)
    parts = line.split(" | ")
    assert parts[4] == "unit.formatter"
    assert parts[5] == "req-789"
    payload = json.loads(parts[6])
    assert payload["extra_field"] == "value"
    assert payload["message"] == "format me"
    assert payload["service"] == "reveal-market"


def test_request_id_context_round_trip():
    token = shared_logging.set_request_id("req-1")
    try:
        assert shared_logging.get_request_id() == "req-1"
    finally:
        shared_logging.reset_request_id(token)
    assert shared_logging.get_request_id() is None


def test_start_heartbeat_logger_emits_until_stopped(monkeypatch):
    events: list[str] = []

    def fake_log_event(logger, level, event, message, **fields):
        events.append(event)

    monkeypatch.setattr(shared_logging, "log_event", fake_log_event)
    logger = logging.getLogger("shared.logging.heartbeat")
    stop_event = shared_logging.start_heartbeat_logger(
        logger,
        "worker-service",
        interval_seconds=0.01,
        message="worker alive",
    )
    try:
        time.sleep(0.03)
    finally:
        stop_event.set()
        time.sleep(0.01)
    assert "service.heartbeat" in events
    assert events[-1] == "service.heartbeat.stop"
