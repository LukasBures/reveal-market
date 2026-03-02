#!/usr/bin/env bash
# Run Hedger pytest suite with consistent worker fan-out and venv discovery.
# Mirrors the backend runner style so local + CI behave the same.

set -euo pipefail

timestamp() {
  date +"%Y-%m-%d %H:%M:%S"
}

log_step() {
  printf '\n[%s] >>> %s\n' "$(timestamp)" "$*"
}

log_error() {
  printf '[%s] ERROR: %s\n' "$(timestamp)" "$*" >&2
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${ROOT_DIR}/.." && pwd)"
export PYTHONPATH="${ROOT_DIR}:${REPO_ROOT}/backend:${PYTHONPATH:-}"

activate_venv() {
  local venv_path="${ROOT_DIR}/.venv"
  local activate_path="${venv_path}/bin/activate"
  if [[ ! -x "${venv_path}/bin/python" ]]; then
    log_error "Expected virtualenv at ${venv_path}. Run 'uv sync --project hedger --extra dev --no-install-project' first."
    exit 1
  fi
  if [[ ! -f "${activate_path}" ]]; then
    log_error "Activate script missing at ${activate_path}"
    exit 1
  fi
  # shellcheck disable=SC1090
  source "${activate_path}"
}

calc_pytest_workers() {
  local override="${PYTEST_WORKER_COUNT:-}"
  if [[ -n "${override}" ]]; then
    echo "${override}"
    return
  fi
  local cpu_count
  if command -v nproc >/dev/null 2>&1; then
    cpu_count="$(nproc)"
  else
    cpu_count="$(sysctl -n hw.ncpu 2>/dev/null || echo 4)"
  fi
  local workers=$((cpu_count - 2))
  if [[ "${workers}" -lt 1 ]]; then
    workers=1
  fi
  echo "${workers}"
}

run_py_tests() {
  cd "${ROOT_DIR}"

  local workers="${PYTEST_WORKER_COUNT:-$(calc_pytest_workers)}"
  local -a pytest_args=()
  local plugin_autoload_disabled="${PYTEST_DISABLE_PLUGIN_AUTOLOAD:-}"

  local venv_path="${ROOT_DIR}/.venv"
  local python_bin="${venv_path}/bin/python"
  local ruff_bin="${venv_path}/bin/ruff"
  activate_venv

  # Ensure dev deps (including xdist) are present.
  if ! "${python_bin}" -c "import pytest, pytest_asyncio, importlib.util; importlib.util.find_spec('xdist')" >/dev/null 2>&1; then
    log_step "Installing dev dependencies (including xdist)"
    if command -v uv >/dev/null 2>&1; then
      uv sync --project "${ROOT_DIR}" --extra dev --no-install-project
    else
      log_error "uv not found on PATH; install uv or run 'uv sync --project hedger --extra dev --no-install-project'"
      exit 1
    fi
  fi

  # Lint first if ruff is available.
  if [[ -x "${ruff_bin}" ]]; then
    log_step "ruff check (hedger)"
    "${ruff_bin}" check app tests
  fi

  if [[ -n "${plugin_autoload_disabled}" && "${plugin_autoload_disabled}" != "0" ]]; then
    pytest_args+=("-p" "pytest_asyncio.plugin")
  fi

  if [[ -n "${workers}" && "${workers}" =~ ^[0-9]+$ && "${workers}" -gt 1 ]]; then
    XDIST_AVAILABLE=$("${python_bin}" - <<'PY'
import importlib.util
print("yes" if importlib.util.find_spec("xdist") or importlib.util.find_spec("pytest_xdist") else "no")
PY
)
    if [[ "$XDIST_AVAILABLE" == "yes" ]]; then
      if [[ -n "${plugin_autoload_disabled}" && "${plugin_autoload_disabled}" != "0" ]]; then
        pytest_args+=("-p" "xdist.plugin")
      fi
      pytest_args+=("-n" "${workers}")
    else
      log_step "pytest-xdist not installed; running single-worker (set PYTEST_WORKER_COUNT=1 or install xdist)"
    fi
  fi

  log_step "pytest (hedger) args=${pytest_args[*]:-single}"
  "${python_bin}" -m pytest "${pytest_args[@]}"
}

run_py_tests
