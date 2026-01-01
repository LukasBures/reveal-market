#!/usr/bin/env bash
set -euo pipefail

# End-to-end MVP readiness runner. Execute from repo root.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> backend: ./backend/run_tests.sh"
pushd "$ROOT" >/dev/null
./backend/run_tests.sh
popd >/dev/null

echo "==> frontend: lint + test + build (requires live backend at /health)"
pushd "$ROOT/frontend" >/dev/null
npm run lint
npm run test
npm run build
popd >/dev/null

echo "==> contracts: ./contracts/run_local.sh full"
pushd "$ROOT/contracts" >/dev/null
./run_local.sh full
popd >/dev/null

if [[ -f "$ROOT/prover/cmd/verify-artifacts" && -x "$ROOT/prover/cmd/verify-artifacts" ]]; then
  echo "==> prover: verifying artifacts"
  pushd "$ROOT/prover" >/dev/null
  ./cmd/verify-artifacts
  popd >/dev/null
elif [[ -d "$ROOT/prover/cmd/verify-artifacts" ]]; then
  if command -v go >/dev/null 2>&1; then
    echo "==> prover: verifying artifacts (go run)"
    pushd "$ROOT/prover" >/dev/null
    go run ./cmd/verify-artifacts
    popd >/dev/null
  else
    echo "==> prover: skip (go not found; run 'go run ./cmd/verify-artifacts')"
  fi
else
  echo "==> prover: skip (prover/cmd/verify-artifacts not found)"
fi

echo "MVP test matrix complete."
