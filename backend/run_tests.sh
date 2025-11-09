#!/usr/bin/env bash
# Run backend pytest suites (API + worker) from a single entrypoint. This probes
# for Poetry/.venv before falling back to system Python so local + CI behave the
# same way.

set -euo pipefail

# Resolve repo root once so PYTHONPATH includes both services. Allow overrides
# via PYTHON_BIN for hermetic builds.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_PY_BIN="${PYTHON_BIN:-$(command -v python3.13 2>/dev/null || command -v python3 2>/dev/null || command -v python 2>/dev/null)}"
export PYTHONPATH="${REPO_ROOT}/backend:${PYTHONPATH:-}"

pip_install_requirements() {
  local service_dir="$1"
  local req_file="${service_dir}/requirements-dev.txt"
  # requirements-dev.txt is generated from Poetry; keep this fallback for
  # environments where Poetry is unavailable (e.g., slim CI images).
  if [[ ! -f "${req_file}" ]]; then
    echo "Error: Unable to install dependencies for ${service_dir} (missing requirements-dev.txt)." >&2
    return 1
  fi
  if [[ -z "${DEFAULT_PY_BIN}" ]]; then
    echo "Error: no python interpreter found (looked for python3.13/python3/python)." >&2
    return 1
  fi
  echo "pip install -r ${req_file}"
  "${DEFAULT_PY_BIN}" -m pip install -r "${req_file}"
}

run_py_tests() {
  local service_dir="$1"
  echo "==> Running pytest in ${service_dir}"
  pushd "${service_dir}" >/dev/null
  # Preference order:
  # 1. Local virtualenvs (.venv) – quickest way to test without touching system env.
  if [[ -f ".venv/bin/activate" ]]; then
    (
      set +u
      # shellcheck disable=SC1091
      source ".venv/bin/activate"
      set -u
      python -m pytest
    )
  # 2. Poetry – standard workflow for the repo. Use `poetry run pytest`.
  elif [[ -f "poetry.lock" ]]; then
    if command -v poetry >/dev/null 2>&1; then
      poetry run pytest
    else
      echo "Warning: 'poetry' not found. Falling back to pip install using requirements-dev.txt."
      pip_install_requirements "${PWD}"
      "${DEFAULT_PY_BIN}" -m pytest
    fi
  # 3. Plain python interpreter – last resort for minimal environments.
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
