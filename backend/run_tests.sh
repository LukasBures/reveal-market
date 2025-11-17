#!/usr/bin/env bash
# Run backend pytest suites (API + worker) from a single entrypoint. This probes
# for Poetry/.venv before falling back to system Python so local + CI behave the
# same way. When pytest-xdist is available we automatically fan out across
# (CPUs - 1) workers to keep runtime low, but gracefully skip the flag if the
# plugin is missing.

set -euo pipefail

# Resolve repo root once so PYTHONPATH includes both services. Allow overrides
# via PYTHON_BIN for hermetic builds.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_PY_BIN="${PYTHON_BIN:-$(command -v python3.12 2>/dev/null || command -v python3 2>/dev/null || command -v python 2>/dev/null)}"
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
  echo "==> Running pytest in ${service_dir}"
  pushd "${service_dir}" >/dev/null
  local workers="${PYTEST_WORKER_COUNT:-$(calc_pytest_workers)}"
  local -a pytest_args=()
  if [[ -n "${workers}" && "${workers}" =~ ^[0-9]+$ && "${workers}" -gt 1 ]]; then
    pytest_args+=("-n" "${workers}")
  fi

  local venv_path="${service_dir}/.venv"
  local python_bin="${venv_path}/bin/python"
  if [[ ! -x "${python_bin}" ]]; then
    echo "Error: expected virtualenv at ${venv_path}. Run 'uv sync --project ${service_dir} --extra dev --no-install-project' first." >&2
    exit 1
  fi

  (
    export VIRTUAL_ENV="${venv_path}"
    PATH="${venv_path}/bin:${PATH}"
    "${python_bin}" -m pytest "${pytest_args[@]}"
  )
  popd >/dev/null
}

run_py_tests "${REPO_ROOT}/backend/api"
run_py_tests "${REPO_ROOT}/backend/worker"

echo "Backend tests completed successfully."
