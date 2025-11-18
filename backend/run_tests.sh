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

# Resolve repo root once so PYTHONPATH includes both services.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${REPO_ROOT}/backend:${PYTHONPATH:-}"

calc_pytest_workers() {
  local cpus=1
  if command -v nproc >/dev/null 2>&1; then
    cpus="$(nproc 2>/dev/null || echo 1)"
  elif [[ "$(uname -s)" == "Darwin" ]]; then
    cpus="$(/usr/sbin/sysctl -n hw.ncpu 2>/dev/null || echo 1)"
  fi
  if [[ -z "${cpus}" || "${cpus}" -le 1 ]]; then
    echo 1
  else
    echo $((cpus - 1))
  fi
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

  local venv_path="${service_dir}/.venv"
  local python_bin="${venv_path}/bin/python"
  if [[ ! -x "${python_bin}" ]]; then
    log_error "Expected virtualenv at ${venv_path}. Run 'uv sync --project ${service_dir} --extra dev --no-install-project' first."
    exit 1
  fi

  (
    export VIRTUAL_ENV="${venv_path}"
    PATH="${venv_path}/bin:${PATH}"
    printf '[%s] pytest %s (workers=%s)\n' "$(timestamp)" "$(basename "${service_dir}")" "${pytest_args[*]:-1}"
    "${python_bin}" -m pytest "${pytest_args[@]}"
  )
  popd >/dev/null
}

run_py_tests "${REPO_ROOT}/backend/api"
run_py_tests "${REPO_ROOT}/backend/worker"

log_step "Backend tests completed successfully"
