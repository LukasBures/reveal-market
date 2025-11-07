#!/usr/bin/env bash
# Run backend pytest suites (API + worker) from a single entrypoint.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_PY_BIN="${PYTHON_BIN:-$(command -v python3.13 2>/dev/null || command -v python3 2>/dev/null || command -v python 2>/dev/null)}"

require_command() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Error: '${cmd}' is not installed or not on PATH." >&2
    exit 1
  fi
}

run_py_tests() {
  local service_dir="$1"
  echo "==> Running pytest in ${service_dir}"
  pushd "${service_dir}" >/dev/null
  if [[ -f ".venv/bin/activate" ]]; then
    (
      set +u
      # shellcheck disable=SC1091
      source ".venv/bin/activate"
      set -u
      python -m pytest
    )
  elif [[ -f "poetry.lock" ]]; then
    require_command poetry
    poetry run pytest
  else
    if [[ -z "${DEFAULT_PY_BIN}" ]]; then
      echo "Error: no python interpreter found (looked for python3.13/python3/python)." >&2
      exit 1
    fi
    "${DEFAULT_PY_BIN}" -m pytest
  fi
  popd >/dev/null
}

run_py_tests "${REPO_ROOT}/backend/api"
run_py_tests "${REPO_ROOT}/backend/worker"

echo "Backend tests completed successfully."
