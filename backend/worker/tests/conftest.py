from __future__ import annotations

import sys
from pathlib import Path


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
