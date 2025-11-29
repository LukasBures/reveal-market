#!/usr/bin/env bash
# Run worker pytest suite using the project virtualenv. Mirrors backend/run_tests.sh but scoped to the worker.

set -euo pipefail

timestamp() { date +"%Y-%m-%d %H:%M:%S"; }
log() { printf '[%s] %s\n' "$(timestamp)" "$*"; }
err() { printf '[%s] ERROR: %s\n' "$(timestamp)" "$*" >&2; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKER_DIR="${ROOT}/worker"
VENV="${WORKER_DIR}/.venv"

if [[ ! -x "${VENV}/bin/python" ]]; then
  err "Expected virtualenv at ${VENV}. Run 'uv sync --project backend/worker --extra dev --no-install-project' first."
  exit 1
fi

calc_workers() {
  local override="${PYTEST_WORKER_COUNT:-}"
  if [[ -n "${override}" ]]; then
    echo "${override}"
    return
  fi
  echo 4
}

workers="$(calc_workers)"
args=()
if [[ -n "${workers}" && "${workers}" =~ ^[0-9]+$ && "${workers}" -gt 1 ]]; then
  args+=("-n" "${workers}")
fi

log "pytest worker (workers=${args[*]:-1})"
(
  export VIRTUAL_ENV="${VENV}"
  PATH="${VENV}/bin:${PATH}"
  export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"
  pushd "${WORKER_DIR}" >/dev/null
  python -m pytest "${args[@]}"
  popd >/dev/null
)

log "worker tests completed successfully"
