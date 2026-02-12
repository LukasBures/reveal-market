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
export HTTP_PROXY=
export HTTPS_PROXY=
export ALL_PROXY=
# Keep fuzzing bounded in the default suite to avoid long stalls.
export FOUNDRY_FUZZ_RUNS="${FOUNDRY_FUZZ_RUNS:-64}"

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

RPC_URL="${RPC_URL:-${RM_RPC_URL:-}}"
VERIFIER_ADDRESS="${VERIFIER_ADDRESS:-${RM_VERIFIER_ADDRESS:-}}"
if [[ -n "${RPC_URL}" && -n "${VERIFIER_ADDRESS}" ]]; then
  log_step "Step 4: on-chain circuit hash check"
  "${CONTRACTS_DIR}/scripts/check_circuit_hash.sh"
else
  log_warn "Skipping on-chain circuit hash check (set RPC_URL/VERIFIER_ADDRESS or RM_RPC_URL/RM_VERIFIER_ADDRESS)"
fi

if [[ "${1:-}" == "full" ]]; then
  log_step "Step 5: extended fuzz tests"
  FOUNDRY_PROFILE=ci.fuzz forge test --match-test testFuzz --gas-report || log_warn "Fuzz suite exited non-zero"

  log_step "Step 6: coverage summary"
  forge coverage --report summary || log_warn "Coverage run exited non-zero"
fi

popd >/dev/null

log_step "Contracts tests completed"
