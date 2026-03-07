#!/usr/bin/env bash
set -euo pipefail

timestamp() { date +"%Y-%m-%d %H:%M:%S"; }
log_step() { printf '\n[%s] >>> %s\n' "$(timestamp)" "$*"; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${ROOT_DIR}/.." && pwd)"
export PYTHONPATH="${ROOT_DIR}:${REPO_ROOT}/backend:${PYTHONPATH:-}"

cd "$ROOT_DIR"

ACTIVATE_PATH="${ROOT_DIR}/.venv/bin/activate"
if [[ -f "$ACTIVATE_PATH" ]]; then
  # shellcheck disable=SC1090
  source "$ACTIVATE_PATH"
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "Python 3.12 interpreter not found (expected ${ROOT_DIR}/.venv/bin/python or python3 on PATH)" >&2
  exit 1
fi

"$PYTHON_BIN" - <<'PY'
import sys
major, minor = sys.version_info[:2]
if (major, minor) != (3, 12):
    raise SystemExit(f"streamer requires Python 3.12, found {major}.{minor}")
PY

# Install dev dependencies if missing.
if ! "$PYTHON_BIN" -c "import pytest, pytest_asyncio, prometheus_client, xdist, websocket, mypy" >/dev/null 2>&1; then
  "$PYTHON_BIN" -m ensurepip --upgrade >/dev/null 2>&1 || true
  "$PYTHON_BIN" -m pip install --no-cache-dir -e .[dev]
fi

CONFIG_PATH="${ROOT_DIR}/../pyproject.toml"
TARGET_PATH="${ROOT_DIR}/app"

log_step "Running mypy (streamer)"
MYPYPATH="${REPO_ROOT}/backend:${ROOT_DIR}:${MYPYPATH:-}" "$PYTHON_BIN" -m mypy --config-file "${CONFIG_PATH}" "${TARGET_PATH}"

PYTEST_ARGS=()
# When plugin autoloading is disabled (e.g., in CI), explicitly enable the plugins we rely on.
if [[ -n "${PYTEST_DISABLE_PLUGIN_AUTOLOAD:-}" ]]; then
  PYTEST_ARGS+=(-p pytest_asyncio)
fi

if [[ -n "${PYTEST_WORKER_COUNT:-}" ]]; then
  WORKERS="${PYTEST_WORKER_COUNT}"
else
  if command -v nproc >/dev/null 2>&1; then
    CPU_COUNT="$(nproc)"
  else
    CPU_COUNT="$(sysctl -n hw.ncpu 2>/dev/null || echo 4)"
  fi
  WORKERS=$((CPU_COUNT - 2))
  if [[ "$WORKERS" -lt 1 ]]; then
    WORKERS=1
  fi
fi
XDIST_AVAILABLE=$("$PYTHON_BIN" - <<'PY'
import importlib.util
print("yes" if importlib.util.find_spec("xdist") or importlib.util.find_spec("pytest_xdist") else "no")
PY
)

if [[ "$WORKERS" =~ ^[0-9]+$ && "$WORKERS" -gt 1 && "$XDIST_AVAILABLE" == "yes" ]]; then
  if [[ -n "${PYTEST_DISABLE_PLUGIN_AUTOLOAD:-}" ]]; then
    PYTEST_ARGS+=(-p pytest_xdist)
  fi
  log_step "pytest (streamer) workers=${WORKERS}"
  exec "$PYTHON_BIN" -m pytest "${PYTEST_ARGS[@]}" -n "$WORKERS"
fi

log_step "pytest (streamer) workers=1"
exec "$PYTHON_BIN" -m pytest "${PYTEST_ARGS[@]}"
