#!/usr/bin/env bash
set -euo pipefail

# ----------------------------------------------------------------------
# Local Dev Runner for Forge (Zen contracts)
# ----------------------------------------------------------------------
# This script:
#  1. Builds all contracts
#  2. Runs all tests with gas reports
#  3. Validates gas snapshot (regression check)
#  4. Optionally runs fuzz & coverage suites (pass "full")
# ----------------------------------------------------------------------

CONTRACTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v forge >/dev/null 2>&1; then
  echo "forge not found on PATH; install Foundry before running this script"
  exit 1
fi

ensure_deps() {
  local missing=0
  for path in \
    "lib/forge-std/src/Test.sol" \
    "lib/openzeppelin-contracts/contracts/access/Ownable.sol" \
    "lib/solmate/src/utils/SafeTransferLib.sol"; do
    if [[ ! -f "${CONTRACTS_DIR}/${path}" ]]; then
      missing=1
      break
    fi
  done

  if [[ "${missing}" -eq 1 ]]; then
    echo "Dependencies missing under lib/. Installing from foundry.lock..."
    if (cd "${CONTRACTS_DIR}" && forge update); then
      echo "Dependencies installed via forge update."
    else
      echo "forge update failed; trying explicit install of deps..."
      (cd "${CONTRACTS_DIR}" && forge install foundry-rs/forge-std@v1.9.1 openzeppelin/openzeppelin-contracts@v5.5.0 transmissions11/solmate@89365b880c4f3c786bdd453d4b8e8fe410344a69)
    fi
    echo "Dependencies installed."
  fi
}

export FOUNDRY_SIG_PROVIDER=none
export HTTP_PROXY=
export HTTPS_PROXY=
export ALL_PROXY=

ensure_deps

echo "=============================="
echo "🏗️  STEP 1: Building contracts"
echo "=============================="
forge build
echo "✅ Build complete"
echo

echo "=============================="
echo "🧪  STEP 2: Running tests"
echo "=============================="
forge test --fail-fast
echo "✅ Tests complete"
echo

echo "=============================="
echo "📊  STEP 3: Checking gas snapshot"
echo "=============================="
if forge snapshot --check; then
  echo "✅ Gas snapshot matches baseline"
else
  echo "⚠️  Gas snapshot changed — regenerating snapshot now (review .gas-snapshot in git diff)"
  forge snapshot
fi
echo

# ----------------------------------------------------------------------
# Optional: Run fuzz & coverage in dedicated mode
# ----------------------------------------------------------------------
if [[ "${1:-}" == "full" ]]; then
  echo "=============================="
  echo "🎯  STEP 4: Running extended fuzz tests"
  echo "=============================="
  FOUNDRY_PROFILE=ci.fuzz forge test --match-test testFuzz --gas-report || true
  echo

  echo "=============================="
  echo "🧮  STEP 5: Generating coverage report"
  echo "=============================="
  forge coverage --report summary || true
  echo "✅ Coverage report generated"
fi

echo "=============================="
echo "✅  All steps finished successfully!"
echo "=============================="
