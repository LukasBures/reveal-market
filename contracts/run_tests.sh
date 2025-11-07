#!/usr/bin/env bash
# Run Foundry build/tests for the contracts workspace.

set -euo pipefail

CONTRACTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v forge >/dev/null 2>&1; then
  echo "Skipping contracts tests: forge not found on PATH" >&2
  exit 0
fi

pushd "${CONTRACTS_DIR}" >/dev/null
forge build
forge test
popd >/dev/null

echo "Contracts tests completed successfully."
