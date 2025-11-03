#!/usr/bin/env bash
# Run the full test suite (backend API, backend worker, smart contracts).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
    require_command python
    python -m pytest
  fi
  popd >/dev/null
}

run_contract_tests() {
  local contracts_dir="$1"
  echo "==> Running forge build/test in ${contracts_dir}"
  pushd "${contracts_dir}" >/dev/null
  if ! command -v forge >/dev/null 2>&1; then
    echo "Skipping contracts tests: forge not found on PATH"
  else
    forge build
    forge test
  fi
  popd >/dev/null
}

run_py_tests "${ROOT_DIR}/backend/api"
run_py_tests "${ROOT_DIR}/backend/worker"
run_contract_tests "${ROOT_DIR}/contracts"

echo "All test suites completed successfully."
