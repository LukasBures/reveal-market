from __future__ import annotations

import asyncio
import sys
import warnings
from pathlib import Path

import pytest


def _prefer_worker_package() -> None:
    """Ensure the worker's ``app`` package shadows the API package in tests."""

    worker_root = Path(__file__).resolve().parents[1]
    repo_root = worker_root.parent
    api_path = repo_root / "api"

    worker_str = str(worker_root)
    if worker_str not in sys.path:
        sys.path.insert(0, worker_str)

    api_str = str(api_path)
    sys.path[:] = [p for p in sys.path if p != api_str]

    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name)


_prefer_worker_package()


@pytest.fixture(scope="session", autouse=True)
def _close_pytest_asyncio_loop():
    """Close any event loop left behind by pytest-asyncio's cleanup helper."""

    yield
    policy = asyncio.get_event_loop_policy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            loop = policy.get_event_loop()
        except RuntimeError:
            loop = getattr(getattr(policy, "_local", None), "_loop", None)
    if loop and not loop.is_closed():
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            policy.set_event_loop(None)
        except RuntimeError:
            return


@pytest.fixture(autouse=True)
def _close_loop_after_test():
    """Ensure clean event loop state between tests to silence ResourceWarnings."""

    yield
    policy = asyncio.get_event_loop_policy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            loop = policy.get_event_loop()
        except RuntimeError:
            loop = getattr(getattr(policy, "_local", None), "_loop", None)
    if loop and not loop.is_closed():
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            policy.set_event_loop(None)
        except RuntimeError:
            return
