#!/usr/bin/env bash
set -euo pipefail

# ----------------------------------------------------------------------
# Extend a market's claim deadline through the MarketFactory.
# ----------------------------------------------------------------------
# Required env:
#   PRIVATE_KEY
#   RPC_URL (or RM_RPC_URL)
#   FACTORY_ADDRESS (or RM_FACTORY_ADDRESS)
#   MARKET_ADDRESS or MARKET_ID
#   NEW_CLAIM_DEADLINE (unix timestamp) OR CLAIM_DEADLINE_EXTENSION_SECONDS
# Optional:
#   CAST_SEND_ARGS   Extra args to append to cast send (e.g., --legacy)
#   ENV_FILE         Path to env file (default: contracts/zen/.env)
# ----------------------------------------------------------------------

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if ! command -v cast >/dev/null 2>&1; then
  echo "cast not found on PATH; install Foundry before running this script" >&2
  exit 1
fi

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

RPC_URL="${RPC_URL:-${RM_RPC_URL:-}}"
FACTORY_ADDRESS="${FACTORY_ADDRESS:-${RM_FACTORY_ADDRESS:-}}"
MARKET_ADDRESS="${MARKET_ADDRESS:-${RM_MARKET_ADDRESS:-}}"

require_env "PRIVATE_KEY"
require_env "RPC_URL"
require_env "FACTORY_ADDRESS"

if [[ -z "${MARKET_ADDRESS}" ]]; then
  if [[ -z "${MARKET_ID:-}" ]]; then
    echo "Missing MARKET_ADDRESS or MARKET_ID" >&2
    exit 1
  fi
  MARKET_ADDRESS="$(cast call "${FACTORY_ADDRESS}" "marketAddress(uint256)(address)" "${MARKET_ID}" --rpc-url "${RPC_URL}")"
fi

if [[ -z "${MARKET_ADDRESS}" || "${MARKET_ADDRESS}" == "0x0000000000000000000000000000000000000000" ]]; then
  echo "Invalid MARKET_ADDRESS" >&2
  exit 1
fi

current_deadline="$(cast call "${MARKET_ADDRESS}" "claimDeadline()(uint256)" --rpc-url "${RPC_URL}")"
if [[ -z "${NEW_CLAIM_DEADLINE:-}" ]]; then
  if [[ -z "${CLAIM_DEADLINE_EXTENSION_SECONDS:-}" ]]; then
    echo "Missing NEW_CLAIM_DEADLINE or CLAIM_DEADLINE_EXTENSION_SECONDS" >&2
    exit 1
  fi
  now_ts="$(date +%s)"
  base_deadline="${current_deadline:-0}"
  if [[ "${base_deadline}" -lt "${now_ts}" ]]; then
    base_deadline="${now_ts}"
  fi
  NEW_CLAIM_DEADLINE="$((base_deadline + CLAIM_DEADLINE_EXTENSION_SECONDS))"
fi

if [[ -n "${current_deadline}" && "${NEW_CLAIM_DEADLINE}" -le "${current_deadline}" ]]; then
  echo "NEW_CLAIM_DEADLINE must be greater than current claimDeadline (${current_deadline})" >&2
  exit 1
fi

CAST_SEND_ARGS_ARRAY=()
if [[ -n "${CAST_SEND_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  CAST_SEND_ARGS_ARRAY=(${CAST_SEND_ARGS})
fi

echo "Extending claim deadline for ${MARKET_ADDRESS} to ${NEW_CLAIM_DEADLINE} (current=${current_deadline})"
cast send --rpc-url "${RPC_URL}" --private-key "${PRIVATE_KEY}" \
  "${CAST_SEND_ARGS_ARRAY[@]}" \
  "${FACTORY_ADDRESS}" \
  "extendMarketClaimDeadline(address,uint256)" \
  "${MARKET_ADDRESS}" \
  "${NEW_CLAIM_DEADLINE}"
