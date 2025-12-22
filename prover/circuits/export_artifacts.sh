#!/usr/bin/env bash
set -euo pipefail

# Generate Groth16 assets and copy them into the vetted artifacts store
# (defaults to prover/artifacts, which is a git submodule). Override DEST to
# export elsewhere.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEST="${DEST:-$ROOT_DIR/prover/artifacts}"

for cmd in jq; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
done

echo "Generating settlement artifacts..."
"$SCRIPT_DIR/generate_keys.sh"

mkdir -p \
  "$DEST/prover/circuits/build" \
  "$DEST/contracts/cache" \
  "$DEST/contracts/zen/cache"

for f in settlement_final.zkey settlement_vk.json settlement_hashes.json settlement_deploy.json; do
  cp "$SCRIPT_DIR/build/$f" "$DEST/prover/circuits/build/$f"
done

rm -rf "$DEST/prover/circuits/build/settlement_js"
cp -R "$SCRIPT_DIR/build/settlement_js" "$DEST/prover/circuits/build/settlement_js"

rm -rf "$DEST/prover/circuits/build/settlement_cpp"
if [[ -d "$SCRIPT_DIR/build/settlement_cpp" ]]; then
  cp -R "$SCRIPT_DIR/build/settlement_cpp" "$DEST/prover/circuits/build/settlement_cpp"
fi

cp "$SCRIPT_DIR/build/settlement_deploy.json" "$DEST/contracts/cache/settlement-vk.json"
cp "$SCRIPT_DIR/build/settlement_deploy.json" "$DEST/contracts/zen/cache/settlement-vk.json"

circuit_hash="$(jq -r '.circuitHash' "$SCRIPT_DIR/build/settlement_hashes.json")"
echo "Exported artifacts with circuitHash: $circuit_hash"
echo "Destination: $DEST"
echo "Commit/push the artifacts submodule (if used) after reviewing the changes."
