#!/usr/bin/env bash
# Aggregate test runner: backend → contracts → frontend. Mirrors CI order so the
# slowest suites fail earliest when run locally.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

run_section() {
  local name="$1"
  local script_path="$2"

  # Print a consistent block header so logs are easy to scan in CI/CLI.
  echo "=============================="
  echo "Running ${name} tests"
  echo "=============================="

  if [[ ! -x "${script_path}" ]]; then
    echo "Error: ${script_path} is missing or not executable" >&2
    exit 1
  fi

  # Execute the downstream script in-place so each workspace controls its own
  # environment (virtualenv, Foundry, npm, etc.).
  (cd "$(dirname "${script_path}")" && "./$(basename "${script_path}")")
}

run_section "backend" "${ROOT_DIR}/backend/run_tests.sh"
run_section "contracts" "${ROOT_DIR}/contracts/run_tests.sh"
run_section "frontend" "${ROOT_DIR}/frontend/run_tests.sh"

echo "=============================="
echo "All test suites completed."
