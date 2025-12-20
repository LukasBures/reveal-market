#!/usr/bin/env bash
set -euo pipefail

# Fetch Groth16 artifacts from a private archive (tar or zip) and unpack them
# into prover/circuits/build. Requires PROVER_ARTIFACTS_URL (and optionally
# PROVER_ARTIFACTS_SHA256) to be set in the environment.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/circuits/build"
URL="${PROVER_ARTIFACTS_URL:-}"
CHECKSUM="${PROVER_ARTIFACTS_SHA256:-}"
TMP_DIR="$(mktemp -d)"
ARCHIVE_PATH="${TMP_DIR}/prover-artifacts"
EXTRACT_DIR="${TMP_DIR}/extracted"
REQUIRED=(
  "settlement_js/generate_witness.js"
  "settlement_js/settlement.wasm"
  "settlement_final.zkey"
  "settlement_vk.json"
  "settlement_hashes.json"
  "settlement_deploy.json"
)

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

if [[ -z "${URL}" ]]; then
  echo "PROVER_ARTIFACTS_URL is not set; cannot fetch prover circuit artifacts." >&2
  exit 1
fi

mkdir -p "${EXTRACT_DIR}"

echo "Downloading prover artifacts..."
curl -fsSL "${URL}" -o "${ARCHIVE_PATH}"

if [[ -n "${CHECKSUM}" ]]; then
  echo "${CHECKSUM}  ${ARCHIVE_PATH}" | sha256sum -c -
fi

if [[ "${URL}" == *.zip || "${ARCHIVE_PATH}" == *.zip ]]; then
  unzip -q "${ARCHIVE_PATH}" -d "${EXTRACT_DIR}"
elif [[ "${URL}" == *.tar.gz || "${URL}" == *.tgz || "${ARCHIVE_PATH}" == *.tar.gz || "${ARCHIVE_PATH}" == *.tgz ]]; then
  tar -xzf "${ARCHIVE_PATH}" -C "${EXTRACT_DIR}"
else
  tar -xf "${ARCHIVE_PATH}" -C "${EXTRACT_DIR}"
fi

artifact_root=""
while IFS= read -r candidate; do
  missing=0
  for rel in "${REQUIRED[@]}"; do
    if [[ ! -f "${candidate}/${rel}" ]]; then
      missing=1
      break
    fi
  done
  if [[ "${missing}" -eq 0 ]]; then
    artifact_root="${candidate}"
    break
  fi
done < <(find "${EXTRACT_DIR}" -type d | sort)

if [[ -z "${artifact_root}" ]]; then
  echo "Downloaded archive did not contain required prover artifacts." >&2
  exit 1
fi

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"
cp -a "${artifact_root}/." "${BUILD_DIR}/"

echo "Prover artifacts installed to ${BUILD_DIR}."
