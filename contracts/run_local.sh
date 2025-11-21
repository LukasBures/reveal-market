#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLYGON_DIR="${SCRIPT_DIR}/polygon"
ZEN_DIR="${SCRIPT_DIR}/zen"

for workspace in "${POLYGON_DIR}" "${ZEN_DIR}"; do
  if [[ ! -x "${workspace}/run_local.sh" ]]; then
    echo "Workspace runner missing at ${workspace}/run_local.sh" >&2
    exit 1
  fi
done

echo "==== Running POLYGON workspace ===="
(cd "${POLYGON_DIR}" && ./run_local.sh "$@")
echo
echo "==== Running ZEN workspace ===="
(cd "${ZEN_DIR}" && ./run_local.sh "$@")
