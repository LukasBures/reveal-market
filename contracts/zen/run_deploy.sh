#!/usr/bin/env bash
set -euo pipefail

# ----------------------------------------------------------------------
# Deploy helper for Zen contracts
# ----------------------------------------------------------------------
# Wraps the Deploy.s.sol script with required env checks and sensible defaults.
# Required env:
#   PRIVATE_KEY                  Deployer/owner key (0x-prefixed hex)
#   RPC_URL                      Target RPC URL
#   ORACLE_ADDRESS               Oracle address to wire into the factory
#   AUTHORIZATION_SIGNER         Backend commit auth signer (EOA)
#   ZEN_TOKEN_ADDRESS            ERC20 collateral token address (or COLLATERAL_TOKEN)
# Optional:
#   USE_STUB_VERIFIER=1    Use stub verifier (skips SETTLEMENT_VK_JSON/SETTLEMENT_VK_PATH)
#   SETTLEMENT_VK_JSON     Full verifying key JSON when USE_STUB_VERIFIER=0
#   SETTLEMENT_VK_PATH     Path to verifying key JSON (default: ../cache/settlement-vk.json)
#   COLLATERAL_TOKEN       ERC20 collateral token address (fallback if ZEN_TOKEN_ADDRESS unset)
#   CHAIN_ID               Chain id for broadcasting (passed to forge)
#   FORGE_BROADCAST_ARGS   Extra args to append to forge script (e.g., --legacy)
# ----------------------------------------------------------------------

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

if ! command -v forge >/dev/null 2>&1; then
  echo "forge not found on PATH; install Foundry before running this script"
  exit 1
fi

# Pick an env file to source (default to repo .env.production). Override by exporting ENV_FILE before running.
DEFAULT_ENV_FILE="${ROOT_DIR}/.env"
ENV_FILE="${ENV_FILE:-${DEFAULT_ENV_FILE}}"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  echo "Loaded environment from ${ENV_FILE}"
else
  echo "ENV file '${ENV_FILE}' not found; continuing with current environment" >&2
fi

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required env var: ${name}" >&2
    exit 1
  fi
}

require_env "PRIVATE_KEY"
require_env "RPC_URL"
require_env "ORACLE_ADDRESS"
require_env "AUTHORIZATION_SIGNER"
if [[ -z "${ZEN_TOKEN_ADDRESS:-}" && -z "${COLLATERAL_TOKEN:-}" ]]; then
  echo "Missing required env var: ZEN_TOKEN_ADDRESS (or COLLATERAL_TOKEN)" >&2
  exit 1
fi

USE_STUB_VERIFIER="${USE_STUB_VERIFIER:-0}"
if [[ "${USE_STUB_VERIFIER}" != "1" ]]; then
  if [[ -z "${SETTLEMENT_VK_JSON:-}" ]]; then
    DEFAULT_VK_PATH="${ROOT_DIR}/../cache/settlement-vk.json"
    FALLBACK_VK_PATH="${ROOT_DIR}/cache/settlement-vk.json"
    VK_PATH="${SETTLEMENT_VK_PATH:-}"
    if [[ -z "${VK_PATH}" ]]; then
      if [[ -f "${DEFAULT_VK_PATH}" ]]; then
        VK_PATH="${DEFAULT_VK_PATH}"
      elif [[ -f "${FALLBACK_VK_PATH}" ]]; then
        VK_PATH="${FALLBACK_VK_PATH}"
      fi
    fi
    if [[ -n "${VK_PATH}" && -f "${VK_PATH}" ]]; then
      echo "SETTLEMENT_VK_JSON not set; loading from ${VK_PATH}"
      SETTLEMENT_VK_JSON="$(cat "${VK_PATH}")"
    else
      echo "SETTLEMENT_VK_JSON is required when USE_STUB_VERIFIER!=1 (searched ${DEFAULT_VK_PATH} and ${FALLBACK_VK_PATH})" >&2
      exit 1
    fi
  fi
fi

export DEPLOYER_KEY="${PRIVATE_KEY}"
export RPC_URL
export ORACLE_ADDRESS
export AUTHORIZATION_SIGNER
export ZEN_TOKEN_ADDRESS="${ZEN_TOKEN_ADDRESS:-}"
export COLLATERAL_TOKEN="${COLLATERAL_TOKEN:-}"
export USE_STUB_VERIFIER
export SETTLEMENT_VK_JSON="${SETTLEMENT_VK_JSON:-}"
export CHAIN_ID="${CHAIN_ID:-}"
expected_chain_id="${EXPECTED_CHAIN_ID:-${CHAIN_ID:-}}"
if [[ -n "${expected_chain_id}" ]]; then
  actual_chain_id="$(cast chain-id --rpc-url "${RPC_URL}" 2>/dev/null || true)"
  if [[ -n "${actual_chain_id}" && "${actual_chain_id}" != "${expected_chain_id}" ]]; then
    echo "RPC chain id mismatch: expected ${expected_chain_id}, got ${actual_chain_id}" >&2
    exit 1
  fi
fi
export SETTLEMENT_VK_PATH

FOUNDRY_ARGS=(script script/Deploy.s.sol --tc Deploy --rpc-url "${RPC_URL}" --broadcast --private-key "${DEPLOYER_KEY}")
if [[ -n "${CHAIN_ID:-}" ]]; then
  FOUNDRY_ARGS+=(--chain-id "${CHAIN_ID}")
fi
if [[ -n "${FORGE_BROADCAST_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  EXTRA_ARGS=(${FORGE_BROADCAST_ARGS})
  FOUNDRY_ARGS+=("${EXTRA_ARGS[@]}")
fi

# Print command with private key redacted to avoid leaking secrets in logs.
echo "Running forge script with args:"
SKIP_NEXT=false
for arg in forge "${FOUNDRY_ARGS[@]}"; do
  if $SKIP_NEXT; then
    SKIP_NEXT=false
    continue
  fi
  if [[ "${arg}" == "--private-key" ]]; then
    printf '  --private-key [REDACTED]'
    SKIP_NEXT=true
  else
    printf '  %q' "${arg}"
  fi
done
echo

export FOUNDRY_SIG_PROVIDER=none
forge "${FOUNDRY_ARGS[@]}"

# Point to the latest broadcast artifact for downstream consumption.
BROADCAST_DIR="${ROOT_DIR}/broadcast/Deploy.s.sol"
if [[ -n "${CHAIN_ID:-}" && -f "${BROADCAST_DIR}/${CHAIN_ID}/run-latest.json" ]]; then
  echo ""
  echo "Broadcast artifact: ${BROADCAST_DIR}/${CHAIN_ID}/run-latest.json"
fi
