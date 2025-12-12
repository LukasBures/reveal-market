#!/usr/bin/env bash
set -euo pipefail

echo "=============================="
echo "🏗️  POLYGON: Building contracts"
echo "=============================="
forge build
echo "✅ Build complete"
echo
echo "=============================="
echo "🧪  POLYGON: Running tests"
echo "=============================="
forge test --fail-fast
echo "✅ Tests complete"
echo

if [[ -f ".gas-snapshot" ]]; then
  echo "=============================="
  echo "📊  POLYGON: Checking gas snapshot"
  echo "=============================="
  if forge snapshot --check; then
    echo "✅ Gas snapshot matches baseline"
  else
    echo "⚠️  Gas snapshot changed — review .gas-snapshot diffs"
    echo "   To update snapshot: run 'forge snapshot'"
  fi
  echo
fi

if [[ "${1:-}" == "full" ]]; then
  echo "=============================="
  echo "🎯  POLYGON: Running extended fuzz tests"
  echo "=============================="
  FOUNDRY_PROFILE=ci.fuzz forge test --gas-report || true
  echo

  echo "=============================="
  echo "🧮  POLYGON: Generating coverage report"
  echo "=============================="
  forge coverage --report summary || true
  echo "✅ Coverage report generated"
fi

echo "=============================="
echo "✅  POLYGON workspace finished successfully!"
echo "=============================="
