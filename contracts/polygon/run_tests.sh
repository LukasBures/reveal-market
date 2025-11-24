#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${POLYGON_RPC_URL:-}" ]]; then
  echo "POLYGON_RPC_URL is required for tests (fail-fast)" >&2
  exit 1
fi

if [[ ! -x "${SCRIPT_DIR}/run_local.sh" ]]; then
  echo "Base workspace run_local.sh not found at ${SCRIPT_DIR}/run_local.sh" >&2
  exit 1
fi

exec "${SCRIPT_DIR}/run_local.sh" "$@"
