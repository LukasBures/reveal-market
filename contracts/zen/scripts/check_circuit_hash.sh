#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

REPO_ROOT="$(cd "${ROOT_DIR}/../.." && pwd)"
DEFAULT_ENV_FILE="${REPO_ROOT}/.env.production"
ENV_FILE="${ENV_FILE:-${DEFAULT_ENV_FILE}}"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
fi

RPC_URL="${RPC_URL:-${RM_RPC_URL:-}}"
expected_chain_id="${EXPECTED_CHAIN_ID:-${CHAIN_ID:-}}"
if [[ -n "${expected_chain_id}" ]]; then
  actual_chain_id="$(cast chain-id --rpc-url "${RPC_URL}" 2>/dev/null || true)"
  if [[ -n "${actual_chain_id}" && "${actual_chain_id}" != "${expected_chain_id}" ]]; then
    echo "RPC chain id mismatch: expected ${expected_chain_id}, got ${actual_chain_id}" >&2
    exit 1
  fi
fi
VERIFIER_ADDRESS="${VERIFIER_ADDRESS:-${RM_VERIFIER_ADDRESS:-}}"
FACTORY_ADDRESS="${FACTORY_ADDRESS:-${RM_FACTORY_ADDRESS:-}}"
FACTORY_MARKET_ID="${FACTORY_MARKET_ID:-${MARKET_ID:-}}"
EXPECTED_HASH="${CIRCUIT_HASH:-${RM_CIRCUIT_HASH:-}}"

if ! command -v cast >/dev/null 2>&1; then
  echo "cast not found on PATH; install Foundry before running this check" >&2
  exit 1
fi

read_hash_from_file() {
  local path="$1"
  if [[ -f "$path" ]]; then
    python3 - <<'PY' "$path"
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
value = data.get("circuitHash") or data.get("circuit_hash")
if value:
    print(value)
PY
  fi
}

normalize_hex() {
  local value="${1:-}"
  value="$(echo "$value" | tr 'A-Z' 'a-z')"
  value="${value#0x}"
  if [[ -z "$value" ]]; then
    echo ""
  else
    echo "0x${value}"
  fi
}

if [[ -z "${EXPECTED_HASH}" ]]; then
  EXPECTED_HASH="$(read_hash_from_file "${ROOT_DIR}/../cache/settlement-vk.json" || true)"
fi
if [[ -z "${EXPECTED_HASH}" ]]; then
  EXPECTED_HASH="$(read_hash_from_file "${ROOT_DIR}/cache/settlement-vk.json" || true)"
fi
if [[ -z "${EXPECTED_HASH}" ]]; then
  EXPECTED_HASH="$(read_hash_from_file "${ROOT_DIR}/../../prover/circuits/build/settlement_hashes.json" || true)"
fi
if [[ -z "${EXPECTED_HASH}" ]]; then
  echo "Expected circuit hash not found; set CIRCUIT_HASH or ensure contracts/cache/settlement-vk.json exists" >&2
  exit 1
fi

if [[ -z "${RPC_URL}" || -z "${VERIFIER_ADDRESS}" ]]; then
  echo "RPC_URL and VERIFIER_ADDRESS are required for on-chain circuit hash checks" >&2
  exit 1
fi

EXPECTED_HASH="$(normalize_hex "${EXPECTED_HASH}")"
ONCHAIN_HASH="$(cast call "${VERIFIER_ADDRESS}" "circuitHash()(bytes32)" --rpc-url "${RPC_URL}")"
ONCHAIN_HASH="$(normalize_hex "${ONCHAIN_HASH}")"

if [[ "${ONCHAIN_HASH}" != "${EXPECTED_HASH}" ]]; then
  echo "Verifier circuitHash mismatch: expected=${EXPECTED_HASH}, onchain=${ONCHAIN_HASH}" >&2
  exit 1
fi

if [[ -n "${FACTORY_ADDRESS}" && -n "${FACTORY_MARKET_ID}" ]]; then
  MARKET_ADDRESS="$(cast call "${FACTORY_ADDRESS}" "marketAddress(uint256)(address)" "${FACTORY_MARKET_ID}" --rpc-url "${RPC_URL}")"
  MARKET_ADDRESS="$(echo "${MARKET_ADDRESS}" | tr 'A-Z' 'a-z')"
  if [[ -z "${MARKET_ADDRESS}" || "${MARKET_ADDRESS}" == "0x0000000000000000000000000000000000000000" ]]; then
    echo "Factory market address missing for market id ${FACTORY_MARKET_ID}" >&2
    exit 1
  fi
  MARKET_HASH="$(cast call "${MARKET_ADDRESS}" "circuitHash()(bytes32)" --rpc-url "${RPC_URL}")"
  MARKET_HASH="$(normalize_hex "${MARKET_HASH}")"
  if [[ "${MARKET_HASH}" != "${EXPECTED_HASH}" ]]; then
    echo "Factory market circuitHash mismatch: expected=${EXPECTED_HASH}, market=${MARKET_HASH}" >&2
    exit 1
  fi
fi

echo "On-chain circuitHash matches expected ${EXPECTED_HASH}"
