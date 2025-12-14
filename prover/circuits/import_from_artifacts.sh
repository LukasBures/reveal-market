#!/usr/bin/env bash
set -euo pipefail

# Copy vetted artifacts from the submodule into the live build/caches used by
# the prover service and deploy scripts.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SRC="${SRC:-$ROOT_DIR/prover/artifacts/prover/circuits/build}"
DEST="$SCRIPT_DIR/build"

if [ ! -d "$SRC" ]; then
  echo "Artifact source not found: $SRC" >&2
  exit 1
fi

mkdir -p "$DEST"
rm -rf "$DEST"
mkdir -p "$DEST"

cp "$SRC"/settlement_final.zkey "$DEST/"
cp "$SRC"/settlement_vk.json "$DEST/"
cp "$SRC"/settlement_hashes.json "$DEST/"
cp "$SRC"/settlement_deploy.json "$DEST/"
rm -rf "$DEST/settlement_js"
cp -R "$SRC/settlement_js" "$DEST/settlement_js"

# Sync vk caches for deploy scripts.
if [ -f "$ROOT_DIR/prover/artifacts/contracts/cache/settlement-vk.json" ]; then
  cp "$ROOT_DIR/prover/artifacts/contracts/cache/settlement-vk.json" "$ROOT_DIR/contracts/cache/settlement-vk.json"
fi
if [ -f "$ROOT_DIR/prover/artifacts/contracts/zen/cache/settlement-vk.json" ]; then
  cp "$ROOT_DIR/prover/artifacts/contracts/zen/cache/settlement-vk.json" "$ROOT_DIR/contracts/zen/cache/settlement-vk.json"
fi

echo "Imported artifacts from $SRC into $DEST"
