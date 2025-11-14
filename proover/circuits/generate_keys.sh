#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT_DIR/build"
PTAU_FILE="$BUILD_DIR/powersOfTau28_hez_final_12.ptau"
CIRCUIT_FILE="$ROOT_DIR/settlement.circom"

mkdir -p "$BUILD_DIR"

if [[ ! -f "$PTAU_FILE" ]]; then
  echo "Downloading PTAU file..."
  curl -L https://hermez.s3-eu-west-1.amazonaws.com/powersOfTau28_hez_final_12.ptau -o "$PTAU_FILE"
fi

echo "Compiling circuit..."
circom "$CIRCUIT_FILE" --r1cs --wasm --sym -o "$BUILD_DIR"

echo "Running Groth16 setup..."
snarkjs groth16 setup "$BUILD_DIR/settlement.r1cs" "$PTAU_FILE" "$BUILD_DIR/settlement_0000.zkey"
snarkjs zkey contribute "$BUILD_DIR/settlement_0000.zkey" "$BUILD_DIR/settlement_final.zkey" -n "initial contribution"

echo "Exporting verification key..."
snarkjs zkey export verificationkey "$BUILD_DIR/settlement_final.zkey" "$BUILD_DIR/settlement_vk.json"

echo "Done."
echo "  Proving key:      $BUILD_DIR/settlement_final.zkey"
echo "  Verification key: $BUILD_DIR/settlement_vk.json"
