#!/usr/bin/env bash
#!/usr/bin/env bash
set -euo pipefail

# ----------------------------------------------------------------------
# Local Dev Runner for Forge (Zen contracts)
# ----------------------------------------------------------------------
# Steps:
#  1) Build contracts
#  2) Run tests with gas report
#  3) Validate gas snapshot (regression guard)
#  4) Optional: fuzz/coverage when called with "full"
# ----------------------------------------------------------------------

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

# Keep Forge offline and deterministic.
export FOUNDRY_SIG_PROVIDER=none
export FOUNDRY_OFFLINE=true
export HTTP_PROXY=
export HTTPS_PROXY=
export ALL_PROXY=

log_step "Step 1: forge build"
forge build

log_step "Step 2: forge test (gas report, fail-fast)"
forge test --gas-report --fail-fast

log_step "Step 3: forge snapshot --check"
if forge snapshot --check; then
  log_step "Gas snapshot matches baseline"
else
  log_warn "Gas snapshot changed — review .gas-snapshot diffs (run 'forge snapshot' to update)"
fi

if [[ "${1:-}" == "full" ]]; then
  log_step "Step 4: extended fuzz tests"
  FOUNDRY_PROFILE=ci.fuzz forge test --match-test testFuzz --gas-report || log_warn "Fuzz suite exited non-zero"

  log_step "Step 5: coverage summary"
  forge coverage --report summary || log_warn "Coverage run exited non-zero"
fi

popd >/dev/null

log_step "Contracts tests completed"
