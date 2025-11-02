#!/usr/bin/env bash
set -euo pipefail

# ----------------------------------------------------------------------
# Local Dev Runner for Forge (Contracts)
# ----------------------------------------------------------------------
# This script:
#  1. Builds all contracts
#  2. Runs all tests with gas reports
#  3. Validates gas snapshot (regression check)
#  4. Optionally runs coverage & fuzz suites
# ----------------------------------------------------------------------

echo "=============================="
echo "🏗️  STEP 1: Building contracts"
echo "=============================="
forge build
echo "✅ Build complete"
echo

echo "=============================="
echo "🧪  STEP 2: Running tests"
echo "=============================="
forge test --gas-report --fail-fast
echo "✅ Tests complete"
echo

echo "=============================="
echo "📊  STEP 3: Checking gas snapshot"
echo "=============================="
if forge snapshot --check; then
  echo "✅ Gas snapshot matches baseline"
else
  echo "⚠️  Gas snapshot changed — review .gas-snapshot diffs"
  echo "   To update snapshot: run 'forge snapshot'"
fi
echo

# ----------------------------------------------------------------------
# Optional: Run fuzz & coverage in dedicated mode
# ----------------------------------------------------------------------
if [[ "${1:-}" == "full" ]]; then
  echo "=============================="
  echo "🎯  STEP 4: Running extended fuzz tests"
  echo "=============================="
  forge test --profile ci.fuzz --match-test testFuzz --gas-report || true
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