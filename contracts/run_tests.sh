#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="${SCRIPT_DIR}/base"
ZEN_DIR="${SCRIPT_DIR}/zen"

for workspace in "${BASE_DIR}" "${ZEN_DIR}"; do
  if [[ ! -x "${workspace}/run_tests.sh" ]]; then
    echo "Workspace test runner not found at ${workspace}/run_tests.sh" >&2
    exit 1
  fi
done

echo "==== Running BASE workspace tests ===="
(cd "${BASE_DIR}" && ./run_tests.sh "$@")
echo
echo "==== Running ZEN workspace tests ===="
(cd "${ZEN_DIR}" && ./run_tests.sh "$@")
