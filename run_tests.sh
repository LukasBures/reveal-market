#!/usr/bin/env bash
# Aggregate test runner: backend → frontend → contracts. Runs each suite in
# sequence so logs stay clear while still letting each stage use its own
# parallelism (pytest-xdist, Vitest threads, forge, etc.).

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

run_section() {
  local name="$1"
  local script_path="$2"

  log_step "Running ${name} tests"

  if [[ ! -x "${script_path}" ]]; then
    log_error "${script_path} is missing or not executable"
    exit 1
  fi

  (cd "$(dirname "${script_path}")" && "./$(basename "${script_path}")")
}

run_section "backend" "${ROOT_DIR}/backend/run_tests.sh"
run_section "frontend" "${ROOT_DIR}/frontend/run_tests.sh"
run_section "contracts" "${ROOT_DIR}/contracts/run_tests.sh"
run_section "proover" "${ROOT_DIR}/proover/run_tests.sh"

log_step "All test suites completed successfully"
