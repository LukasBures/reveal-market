#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT_DIR/build"
PTAU_FILE="$BUILD_DIR/powersOfTau28_hez_final_12.ptau"
PTAU_MIN_BYTES=1000000
PTAU_URL="${PTAU_URL:-https://storage.googleapis.com/zkevm/ptau/powersOfTau28_hez_final_12.ptau}"
CIRCUIT_FILE="$ROOT_DIR/settlement.circom"
CIRCOM_TAG="${CIRCOM_TAG:-v2.2.3}"
CIRCOM_CACHE_DIR="$BUILD_DIR/.circom-bin"
CIRCOM_BIN="$CIRCOM_CACHE_DIR/circom"
CIRCOMLIB_TAG="${CIRCOMLIB_TAG:-v2.0.5}"
CIRCOMLIB_DIR="$BUILD_DIR/circomlib"
SNARKJS_VERSION="${SNARKJS_VERSION:-0.7.4}"
USE_SYSTEM_SNARKJS="${USE_SYSTEM_SNARKJS:-true}"
CONTRIBUTOR_NAME="${CONTRIBUTOR_NAME:-initial contribution}"
NODE_VERSION="${NODE_VERSION:-v20.18.0}"
NODE_CACHE_DIR="${BUILD_DIR}/.node-runtime"
generate_entropy() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  elif command -v python3 >/dev/null 2>&1; then
    python3 - <<'PY'
import secrets, sys
sys.stdout.write(secrets.token_hex(32))
PY
  else
    date +%s%N
  fi
}

download_circom() {
  local os arch asset url
  os="$(uname -s)"
  arch="$(uname -m)"
  case "${os}" in
    Linux)
      if [[ "${arch}" != "x86_64" ]]; then
        echo "Circom binary releases currently target x86_64 Linux only. Install circom manually for ${arch}." >&2
        exit 1
      fi
      asset="circom-linux-amd64"
      ;;
    Darwin)
      asset="circom-macos-amd64"
      if [[ "${arch}" == "arm64" ]]; then
        echo "Apple Silicon detected; using the x86_64 circom binary (Rosetta required)." >&2
      fi
      ;;
    *)
      echo "Unsupported OS '${os}'. Install circom manually and re-run." >&2
      exit 1
      ;;
  esac
  url="https://github.com/iden3/circom/releases/download/${CIRCOM_TAG}/${asset}"
  mkdir -p "${CIRCOM_CACHE_DIR}"
  echo "Downloading circom ${CIRCOM_TAG} (${asset})..."
  curl -fsSL "${url}" -o "${CIRCOM_BIN}"
  chmod +x "${CIRCOM_BIN}"
}

run_circom() {
  if command -v circom >/dev/null 2>&1; then
    circom "$@"
    return
  fi
  if [[ ! -x "${CIRCOM_BIN}" ]]; then
    download_circom
  fi
  "${CIRCOM_BIN}" "$@"
}

run_snarkjs() {
  if [[ "${USE_SYSTEM_SNARKJS}" == "true" ]] && command -v snarkjs >/dev/null 2>&1; then
    snarkjs "$@"
  else
    if ! command -v npx >/dev/null 2>&1; then
      echo "npx is required to download snarkjs. Install Node.js + npm (e.g., sudo apt install -y nodejs npm)." >&2
      exit 1
    fi
    echo "snarkjs not found; running via npx snarkjs@${SNARKJS_VERSION}..."
    npx --yes "snarkjs@${SNARKJS_VERSION}" "$@"
  fi
}

mkdir -p "$BUILD_DIR"

if [[ ! -d "${CIRCOMLIB_DIR}" ]]; then
  echo "Fetching circomlib ${CIRCOMLIB_TAG}..."
  mkdir -p "${CIRCOMLIB_DIR}"
  curl -fsSL "https://github.com/iden3/circomlib/archive/refs/tags/${CIRCOMLIB_TAG}.tar.gz" \
    | tar -xz --strip-components=1 -C "${CIRCOMLIB_DIR}"
fi

if [[ ! -f "$PTAU_FILE" || $(wc -c <"$PTAU_FILE") -lt ${PTAU_MIN_BYTES} ]]; then
  echo "Downloading PTAU file..."
  curl -L "${PTAU_URL}" -o "$PTAU_FILE"
fi

echo "Compiling circuit..."
run_circom "$CIRCUIT_FILE" --r1cs --wasm --sym -l "$BUILD_DIR" -o "$BUILD_DIR"

echo "Running Groth16 setup..."
run_snarkjs groth16 setup "$BUILD_DIR/settlement.r1cs" "$PTAU_FILE" "$BUILD_DIR/settlement_0000.zkey"
CONTRIBUTOR_ENTROPY="${CONTRIBUTOR_ENTROPY:-$(generate_entropy)}"
printf "%s\n%s\n" "${CONTRIBUTOR_NAME}" "${CONTRIBUTOR_ENTROPY}" \
  | run_snarkjs zkey contribute "$BUILD_DIR/settlement_0000.zkey" "$BUILD_DIR/settlement_final.zkey"

echo "Exporting verification key..."
run_snarkjs zkey export verificationkey "$BUILD_DIR/settlement_final.zkey" "$BUILD_DIR/settlement_vk.json"

echo "Done."
echo "  Proving key:      $BUILD_DIR/settlement_final.zkey"
echo "  Verification key: $BUILD_DIR/settlement_vk.json"
