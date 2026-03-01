from __future__ import annotations

import logging

import pytest
from app import service as service_module
from app.config import Settings
from app.service import HedgerService


@pytest.mark.parametrize("environment", ["dev", "local"])
def test_missing_wallet_logs_warning_in_dev_like_envs(monkeypatch, environment: str):
    levels: list[int] = []

    def _capture_log_event(_logger, level: int, **kwargs):
        if kwargs.get("event") == "hedger.config.missing_wallet":
            levels.append(level)

    monkeypatch.setattr(service_module, "log_event", _capture_log_event)
    HedgerService(Settings(environment=environment, hedger_private_key=None))

    assert levels == [logging.WARNING]


def test_missing_wallet_logs_error_in_prod(monkeypatch):
    levels: list[int] = []

    def _capture_log_event(_logger, level: int, **kwargs):
        if kwargs.get("event") == "hedger.config.missing_wallet":
            levels.append(level)

    monkeypatch.setattr(service_module, "log_event", _capture_log_event)
    HedgerService(Settings(environment="prod", hedger_private_key=None))

    assert levels == [logging.ERROR]
