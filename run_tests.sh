#!/usr/bin/env bash
# Aggregate test runner: backend → frontend → contracts. Runs each suite in
# sequence so logs stay clear while still letting each stage use its own
# parallelism (pytest-xdist, Vitest threads, forge, etc.).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

run_section() {
  local name="$1"
  local script_path="$2"

  echo "=============================="
  echo "Running ${name} tests"
  echo "=============================="

  if [[ ! -x "${script_path}" ]]; then
    echo "Error: ${script_path} is missing or not executable" >&2
    exit 1
  fi

  (cd "$(dirname "${script_path}")" && "./$(basename "${script_path}")")
}

run_section "backend" "${ROOT_DIR}/backend/run_tests.sh"
run_section "frontend" "${ROOT_DIR}/frontend/run_tests.sh"
run_section "contracts" "${ROOT_DIR}/contracts/run_tests.sh"
run_section "proover" "${ROOT_DIR}/proover/run_tests.sh"

echo "=============================="
echo "All test suites completed."
