#!/usr/bin/env bash
# Aggregate test runner for backend + hedger + streamer + relayer + frontend +
# contracts + prover. Runs each suite in sequence so logs stay clear while still
# letting each stage use its own parallelism (pytest-xdist, Vitest threads,
# forge, etc.). Extra CLI args are forwarded to every suite.

set -euo pipefail

timestamp() {
  date +"%Y-%m-%d %H:%M:%S"
}

log_error() {
  printf '[%s] ERROR: %s\n' "$(timestamp)" "$*" >&2
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_ARGS=("$@")
# Default to quieter pytest output unless caller overrides.
export PYTEST_ADDOPTS="${PYTEST_ADDOPTS:--q --disable-warnings}"
LOG_DIR="${ROOT_DIR}/logs/test-runs"
mkdir -p "${LOG_DIR}"
# Colors for TTY output.
if [[ -t 1 ]]; then
  GREEN="$(tput setaf 2 2>/dev/null || true)"
  RED="$(tput setaf 1 2>/dev/null || true)"
  RESET="$(tput sgr0 2>/dev/null || true)"
else
  GREEN="" ; RED="" ; RESET=""
fi

usage() {
  cat <<EOF
Usage: ./run_tests.sh [args...]
Passes any provided arguments through to each suite (e.g., -v, -k <pattern>).
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

run_section() {
  local name="$1"
  local script_path="$2"
  shift 2
  local -a env_vars=("$@")

  local log_file="${LOG_DIR}/$(echo "${name}" | tr '/ ' '__').log"

  if [[ ! -x "${script_path}" ]]; then
    log_error "${script_path} is missing or not executable"
    exit 1
  fi

  # Compact status line similar to pre-commit output.
  local width=68
  local result
  if (cd "$(dirname "${script_path}")" && env "${env_vars[@]}" "./$(basename "${script_path}")" "${SCRIPT_ARGS[@]}") >"${log_file}" 2>&1; then
    result="Passed"
    local dots=$((width - ${#name} - ${#result}))
    ((dots < 2)) && dots=2
    printf '%s' "${name}"
    printf '.%.0s' $(seq 1 "${dots}")
    printf '%s%s%s\n' "${GREEN}" "${result}" "${RESET}"
  else
    result="Failed"
    local dots=$((width - ${#name} - ${#result}))
    ((dots < 2)) && dots=2
    printf '%s' "${name}"
    printf '.%.0s' $(seq 1 "${dots}")
    printf '%s%s%s\n' "${RED}" "${result}" "${RESET}"
    echo "Tail of log (${log_file}):"
    tail -n 200 "${log_file}" || true
    exit 1
  fi
}

run_section "backend" "${ROOT_DIR}/backend/run_tests.sh"
run_section "hedger" "${ROOT_DIR}/hedger/run_tests.sh"
run_section "streamer" "${ROOT_DIR}/streamer/run_tests.sh"
run_section "relayer" "${ROOT_DIR}/relayer/run_tests.sh"
run_section "frontend" "${ROOT_DIR}/frontend/run_tests.sh" FRONTEND_REQUIRE_API="${FRONTEND_REQUIRE_API:-false}"
run_section "contracts/polygon" "${ROOT_DIR}/contracts/polygon/run_tests.sh"
run_section "contracts/zen" "${ROOT_DIR}/contracts/zen/run_tests.sh"
run_section "prover" "${ROOT_DIR}/prover/run_tests.sh"

# Final summary line
final_width=68
final_label="All test suites"
final_result="Passed"
final_dots=$((final_width - ${#final_label} - ${#final_result}))
((final_dots < 2)) && final_dots=2
printf '%s' "${final_label}"
printf '.%.0s' $(seq 1 "${final_dots}")
printf '%s%s%s\n' "${GREEN}" "${final_result}" "${RESET}"
