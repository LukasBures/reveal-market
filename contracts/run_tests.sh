#!/usr/bin/env bash
# Run Foundry build/tests for the contracts workspace. We keep build + test
# separate so `forge test` does not have to recompile everything when cached.

set -euo pipefail

timestamp() {
  date +"%Y-%m-%d %H:%M:%S"
}

log_step() {
  printf '\n[%s] >>> %s\n' "$(timestamp)" "$*"
}

log_warn() {
  printf '[%s] WARN: %s\n' "$(timestamp)" "$*" >&2
}

CONTRACTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v forge >/dev/null 2>&1; then
  log_warn "Skipping contracts tests: forge not found on PATH"
  exit 0
fi

pushd "${CONTRACTS_DIR}" >/dev/null
log_step "forge build"
forge build
log_step "forge test"
forge test
popd >/dev/null

log_step "Contracts tests completed successfully"
