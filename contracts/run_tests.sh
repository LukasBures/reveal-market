#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLYGON_DIR="${SCRIPT_DIR}/polygon"
ZEN_DIR="${SCRIPT_DIR}/zen"

for workspace in "${POLYGON_DIR}" "${ZEN_DIR}"; do
  if [[ ! -x "${workspace}/run_tests.sh" ]]; then
    echo "Workspace test runner not found at ${workspace}/run_tests.sh" >&2
    exit 1
  fi
done

echo "==== Running POLYGON workspace tests ===="
(cd "${POLYGON_DIR}" && ./run_tests.sh "$@")
echo
echo "==== Running ZEN workspace tests ===="
(cd "${ZEN_DIR}" && ./run_tests.sh "$@")
