#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_PATH="${SCRIPT_DIR}/.venv"
ACTIVATE_PATH="${VENV_PATH}/bin/activate"
if [[ ! -x "${VENV_PATH}/bin/python" || ! -f "${ACTIVATE_PATH}" ]]; then
  echo "Expected virtualenv at ${VENV_PATH}. Run 'uv sync --project relayer --extra dev --no-install-project' first." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "${ACTIVATE_PATH}"

export PYTHONPATH=src
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

# Explicitly load pytest-asyncio so async tests run even without plugin autoload tweaks.
printf '\n[%s] >>> %s\n' "$(date +'%Y-%m-%d %H:%M:%S')" "Running pytest (relayer)"
python -m pytest -p pytest_asyncio.plugin "$@"
