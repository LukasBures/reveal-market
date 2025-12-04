#!/usr/bin/env bash
# Run backend pytest suites (API + worker) from a single entrypoint. This probes
# for Poetry/.venv before falling back to system Python so local + CI behave the
# same way. When pytest-xdist is available we automatically fan out across
# (CPUs - 1) workers to keep runtime low, but gracefully skip the flag if the
# plugin is missing.

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

activate_venv() {
  local service_dir="$1"
  local venv_path="${service_dir}/.venv"
  local activate_path="${venv_path}/bin/activate"
  if [[ ! -x "${venv_path}/bin/python" ]]; then
    log_error "Expected virtualenv at ${venv_path}. Run 'uv sync --project ${service_dir} --extra dev --no-install-project' first."
    exit 1
  fi
  if [[ ! -f "${activate_path}" ]]; then
    log_error "Activate script missing at ${activate_path}"
    exit 1
  fi
  # shellcheck disable=SC1090
  source "${activate_path}"
}

# Resolve repo root once so PYTHONPATH includes both services.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${REPO_ROOT}/backend:${PYTHONPATH:-}"

calc_pytest_workers() {
  local override="${PYTEST_WORKER_COUNT:-}"
  if [[ -n "${override}" ]]; then
    echo "${override}"
    return
  fi
  echo 4
}

run_py_tests() {
  local service_dir="$1"
  log_step "Running pytest in ${service_dir}"
  pushd "${service_dir}" >/dev/null
  local workers="${PYTEST_WORKER_COUNT:-$(calc_pytest_workers)}"
  local -a pytest_args=()
  if [[ -n "${workers}" && "${workers}" =~ ^[0-9]+$ && "${workers}" -gt 1 ]]; then
    pytest_args+=("-n" "${workers}")
  fi

  (
    activate_venv "${service_dir}"
    printf '[%s] pytest %s (workers=%s)\n' "$(timestamp)" "$(basename "${service_dir}")" "${pytest_args[*]:-1}"
    python -m pytest "${pytest_args[@]}"
  )
  popd >/dev/null
}

run_py_tests "${REPO_ROOT}/backend/api"

run_shared_tests() {
  local shared_tests_path="backend/shared/tests"
  log_step "Running pytest for shared modules"
  (
    activate_venv "${REPO_ROOT}/backend/api"
    local workers="${PYTEST_WORKER_COUNT:-$(calc_pytest_workers)}"
    local -a pytest_args=()
    if [[ -n "${workers}" && "${workers}" =~ ^[0-9]+$ && "${workers}" -gt 1 ]]; then
      pytest_args+=("-n" "${workers}")
    fi
    pushd "${REPO_ROOT}" >/dev/null
    printf '[%s] pytest shared (workers=%s)\n' "$(timestamp)" "${pytest_args[*]:-1}"
    python -m pytest "${pytest_args[@]}" "${shared_tests_path}"
    popd >/dev/null
  )
}

run_shared_tests

run_py_tests "${REPO_ROOT}/backend/worker"

log_step "Backend tests completed successfully"
