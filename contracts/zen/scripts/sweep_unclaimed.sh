#!/usr/bin/env bash
set -euo pipefail

# ----------------------------------------------------------------------
# Sweep unclaimed payouts after claimDeadline through the MarketFactory.
# ----------------------------------------------------------------------
# Required env:
#   PRIVATE_KEY
#   RPC_URL (or RM_RPC_URL)
#   FACTORY_ADDRESS (or RM_FACTORY_ADDRESS)
#   MARKET_ADDRESS or MARKET_ID
# Optional:
#   RECIPIENT           Explicit recipient address (must be protocolPool or relayerEscrow).
#   RECIPIENT_TYPE      protocol|relayer (default: protocol)
#   CAST_SEND_ARGS      Extra args to append to cast send (e.g., --legacy)
#   ENV_FILE            Path to env file (default: contracts/zen/.env)
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

claim_deadline="$(cast call "${MARKET_ADDRESS}" "claimDeadline()(uint256)" --rpc-url "${RPC_URL}")"
claims_swept="$(cast call "${MARKET_ADDRESS}" "claimsSwept()(bool)" --rpc-url "${RPC_URL}")"
now_ts="$(date +%s)"

if [[ "${claims_swept}" == "true" ]]; then
  echo "Claims already swept for ${MARKET_ADDRESS}" >&2
  exit 1
fi

if [[ -z "${claim_deadline}" || "${claim_deadline}" -eq 0 || "${now_ts}" -le "${claim_deadline}" ]]; then
  echo "Claim deadline not reached (claimDeadline=${claim_deadline}, now=${now_ts}); sweep would revert" >&2
  exit 1
fi

recipient="${RECIPIENT:-}"
if [[ -z "${recipient}" ]]; then
  recipient_type="${RECIPIENT_TYPE:-protocol}"
  case "${recipient_type}" in
    protocol)
      recipient="$(cast call "${MARKET_ADDRESS}" "protocolPool()(address)" --rpc-url "${RPC_URL}")"
      ;;
    relayer)
      recipient="$(cast call "${MARKET_ADDRESS}" "relayerEscrow()(address)" --rpc-url "${RPC_URL}")"
      ;;
    *)
      echo "Invalid RECIPIENT_TYPE: ${recipient_type} (expected protocol or relayer)" >&2
      exit 1
      ;;
  esac
fi

if [[ -z "${recipient}" || "${recipient}" == "0x0000000000000000000000000000000000000000" ]]; then
  echo "Invalid RECIPIENT address" >&2
  exit 1
fi

CAST_SEND_ARGS_ARRAY=()
if [[ -n "${CAST_SEND_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  CAST_SEND_ARGS_ARRAY=(${CAST_SEND_ARGS})
fi

echo "Sweeping unclaimed payouts for ${MARKET_ADDRESS} to ${recipient}"
cast send --rpc-url "${RPC_URL}" --private-key "${PRIVATE_KEY}" \
  "${CAST_SEND_ARGS_ARRAY[@]}" \
  "${FACTORY_ADDRESS}" \
  "sweepUnclaimed(address,address)" \
  "${MARKET_ADDRESS}" \
  "${recipient}"
