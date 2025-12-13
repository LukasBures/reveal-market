#!/usr/bin/env bash
set -euo pipefail

# ----------------------------------------------------------------------
# Deploy helper for Zen contracts
# ----------------------------------------------------------------------
# Wraps the Deploy.s.sol script with required env checks and sensible defaults.
# Required env:
#   DEPLOYER_KEY           Private key for broadcasting (0x-prefixed hex)
#   RPC_URL                Target RPC URL
#   ORACLE_ADDRESS         Oracle address to wire into the factory
#   AUTHORIZATION_SIGNER   Backend commit auth signer
#   ZEN_TOKEN_ADDRESS      ERC20 collateral token address
# Optional:
#   USE_STUB_VERIFIER=1    Use stub verifier (skips SETTLEMENT_VK_JSON)
#   SETTLEMENT_VK_JSON     Full verifying key JSON when USE_STUB_VERIFIER=0
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
DEFAULT_ENV_FILE="${ROOT_DIR}/../../.env.production"
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

require_env "DEPLOYER_KEY"
require_env "RPC_URL"
require_env "ORACLE_ADDRESS"
require_env "AUTHORIZATION_SIGNER"
require_env "ZEN_TOKEN_ADDRESS"

USE_STUB_VERIFIER="${USE_STUB_VERIFIER:-0}"
if [[ "${USE_STUB_VERIFIER}" != "1" ]]; then
  if [[ -z "${SETTLEMENT_VK_JSON:-}" ]]; then
    DEFAULT_VK_PATH="${ROOT_DIR}/cache/settlement_deploy.json"
    echo "$DEFAULT_VK_PATH"
    VK_PATH="${SETTLEMENT_VK_PATH:-${DEFAULT_VK_PATH}}"
    if [[ -f "${VK_PATH}" ]]; then
      echo "SETTLEMENT_VK_JSON not set; loading from ${VK_PATH}"
      SETTLEMENT_VK_JSON="$(cat "${VK_PATH}")"
    else
      echo "SETTLEMENT_VK_JSON is required when USE_STUB_VERIFIER!=1 (fallback file not found at ${VK_PATH})" >&2
      exit 1
    fi
  fi
fi

export DEPLOYER_KEY
export RPC_URL
export ORACLE_ADDRESS
export AUTHORIZATION_SIGNER
export ZEN_TOKEN_ADDRESS
export USE_STUB_VERIFIER
export SETTLEMENT_VK_JSON
export CHAIN_ID
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

echo "Running forge script with args:"
printf '  %q' forge "${FOUNDRY_ARGS[@]}"
echo

export FOUNDRY_SIG_PROVIDER=none
forge "${FOUNDRY_ARGS[@]}"
