#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$ROOT_DIR"

PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Python 3.12 interpreter not found" >&2
  exit 1
fi

"$PYTHON_BIN" - <<'PY'
import sys
major, minor = sys.version_info[:2]
if (major, minor) != (3, 12):
    raise SystemExit(f"price-streamer requires Python 3.12, found {major}.{minor}")
PY

# Install dev dependencies if missing.
if ! "$PYTHON_BIN" -c "import pytest, pytest_asyncio, prometheus_client" >/dev/null 2>&1; then
  "$PYTHON_BIN" -m ensurepip --upgrade >/dev/null 2>&1 || true
  "$PYTHON_BIN" -m pip install --no-cache-dir -e .[dev]
fi

WORKERS="${PYTEST_WORKER_COUNT:-4}"
if [[ "$WORKERS" =~ ^[0-9]+$ && "$WORKERS" -gt 1 ]]; then
  exec "$PYTHON_BIN" -m pytest -n "$WORKERS"
else
  exec "$PYTHON_BIN" -m pytest
fi
