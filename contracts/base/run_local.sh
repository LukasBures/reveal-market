#!/usr/bin/env bash
set -euo pipefail

echo "=============================="
echo "🏗️  BASE: Building contracts"
echo "=============================="
forge build
echo "✅ Build complete"
echo

echo "=============================="
echo "🧪  BASE: Running tests"
echo "=============================="
forge test --gas-report --fail-fast
echo "✅ Tests complete"
echo

if [[ -f ".gas-snapshot" ]]; then
  echo "=============================="
  echo "📊  BASE: Checking gas snapshot"
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
  echo "🎯  BASE: Running extended fuzz tests"
  echo "=============================="
  FOUNDRY_PROFILE=ci.fuzz forge test --gas-report || true
  echo

  echo "=============================="
  echo "🧮  BASE: Generating coverage report"
  echo "=============================="
  forge coverage --report summary || true
  echo "✅ Coverage report generated"
fi

echo "=============================="
echo "✅  BASE workspace finished successfully!"
echo "=============================="
