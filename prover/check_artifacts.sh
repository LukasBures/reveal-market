#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

REQUIRED_FILES=(
  "circuits/build/settlement_final.zkey"
  "circuits/build/settlement_vk.json"
  "circuits/build/settlement_hashes.json"
  "circuits/build/settlement_deploy.json"
  "circuits/build/settlement_js/settlement.wasm"
  "circuits/build/settlement_js/generate_witness.js"
)

if [[ "${PROVER_WITNESS_MODE:-}" == "cpp" ]]; then
  REQUIRED_FILES+=("circuits/build/settlement_cpp/settlement")
fi
if [[ -n "${PROVER_WITNESS_BINARY:-}" ]]; then
  REQUIRED_FILES+=("${PROVER_WITNESS_BINARY}")
fi

missing=0
for path in "${REQUIRED_FILES[@]}"; do
  if [[ ! -s "$path" ]]; then
    echo "Missing or empty artifact: $path" >&2
    missing=1
  fi
done

if [[ $missing -ne 0 ]]; then
  exit 1
fi

echo "Prover artifacts present."
