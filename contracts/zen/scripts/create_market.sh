#!/usr/bin/env bash
set -euo pipefail

# ----------------------------------------------------------------------
# Create a MarketFactory market and emit JSON for backend ingestion.
# ----------------------------------------------------------------------
# Required env:
#   PRIVATE_KEY
#   RPC_URL
#   FACTORY_ADDRESS
#   ORACLE_ADDRESS
#   AUTHORIZATION_SIGNER
#   VERIFIER_ADDRESS
#   CIRCUIT_HASH
#   TICKET_SIZE_WEI
#   MAX_COMMITMENTS
#   PROTOCOL_LIABILITY_CAP_WEI
#   COMMIT_DEADLINE (unix timestamp) OR COMMIT_LEAD_SECONDS
# Optional:
#   CAST_SEND_ARGS   Extra args to append to cast send (e.g., --legacy)
#   OUTPUT_PATH      If set, write JSON output to this path
# ----------------------------------------------------------------------

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if ! command -v cast >/dev/null 2>&1; then
  echo "cast not found on PATH; install Foundry before running this script" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found on PATH; install Python 3 before running this script" >&2
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

require_env "PRIVATE_KEY"
require_env "RPC_URL"
require_env "FACTORY_ADDRESS"
require_env "ORACLE_ADDRESS"
require_env "AUTHORIZATION_SIGNER"
require_env "VERIFIER_ADDRESS"
require_env "CIRCUIT_HASH"
require_env "TICKET_SIZE_WEI"
require_env "MAX_COMMITMENTS"
require_env "PROTOCOL_LIABILITY_CAP_WEI"

now_ts="$(date +%s)"
if [[ -z "${COMMIT_DEADLINE:-}" ]]; then
  if [[ -z "${COMMIT_LEAD_SECONDS:-}" ]]; then
    echo "Missing COMMIT_DEADLINE or COMMIT_LEAD_SECONDS" >&2
    exit 1
  fi
  COMMIT_DEADLINE="$((now_ts + COMMIT_LEAD_SECONDS))"
fi

if [[ "${COMMIT_DEADLINE}" -le "${now_ts}" ]]; then
  echo "COMMIT_DEADLINE must be in the future (now=${now_ts})" >&2
  exit 1
fi

export FACTORY_ADDRESS
export ORACLE_ADDRESS
export AUTHORIZATION_SIGNER
export VERIFIER_ADDRESS
export CIRCUIT_HASH
export COMMIT_DEADLINE
export TICKET_SIZE_WEI
export MAX_COMMITMENTS
export PROTOCOL_LIABILITY_CAP_WEI

expected_market_id="$(cast call "${FACTORY_ADDRESS}" "nextMarketId()(uint256)" --rpc-url "${RPC_URL}")"
predicted_address="$(cast call "${FACTORY_ADDRESS}" "predictMarketAddress(uint256)(address)" "${expected_market_id}" --rpc-url "${RPC_URL}")"
chain_id="$(cast chain-id --rpc-url "${RPC_URL}" 2>/dev/null || true)"
global_rake_bps="$(cast call "${FACTORY_ADDRESS}" "globalRakeBps()(uint256)" --rpc-url "${RPC_URL}" 2>/dev/null || true)"

CAST_SEND_ARGS_ARRAY=()
if [[ -n "${CAST_SEND_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  CAST_SEND_ARGS_ARRAY=(${CAST_SEND_ARGS})
fi

create_payload="(${ORACLE_ADDRESS},${VERIFIER_ADDRESS},${CIRCUIT_HASH},${COMMIT_DEADLINE},${TICKET_SIZE_WEI},${MAX_COMMITMENTS},${AUTHORIZATION_SIGNER},${PROTOCOL_LIABILITY_CAP_WEI})"
tx_json="$(cast send --json --rpc-url "${RPC_URL}" --private-key "${PRIVATE_KEY}" \
  "${CAST_SEND_ARGS_ARRAY[@]}" \
  "${FACTORY_ADDRESS}" \
  "createMarket((address,address,bytes32,uint256,uint256,uint256,address,uint256))" \
  "${create_payload}")"

tx_hash="$(python3 - <<'PY' <<< "${tx_json}"
import json
import sys

data = json.load(sys.stdin)
print(data.get("transactionHash") or data.get("transaction_hash") or "")
PY
)"

if [[ -z "${tx_hash}" ]]; then
  echo "Failed to parse transaction hash from cast output" >&2
  exit 1
fi

receipt_path="$(mktemp)"
cast receipt --json --rpc-url "${RPC_URL}" "${tx_hash}" > "${receipt_path}"

market_created_topic="$(cast keccak "MarketCreated(uint256,address,address,bytes32,uint256,uint256,uint256)")"

export EXPECTED_MARKET_ID="${expected_market_id}"
export PREDICTED_ADDRESS="${predicted_address}"
export TX_HASH="${tx_hash}"
export RECEIPT_PATH="${receipt_path}"
export MARKET_CREATED_TOPIC="${market_created_topic}"
export CHAIN_ID="${chain_id}"
export GLOBAL_RAKE_BPS="${global_rake_bps}"

python3 - <<'PY'
import json
import os
from pathlib import Path

def _as_int(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value, 0)
        except ValueError:
            try:
                return int(value)
            except ValueError:
                return None
    return None

receipt_path = os.environ.get("RECEIPT_PATH")
receipt = {}
if receipt_path:
    receipt = json.loads(Path(receipt_path).read_text())

factory = os.environ.get("FACTORY_ADDRESS", "").lower()
topic0 = os.environ.get("MARKET_CREATED_TOPIC", "").lower()
market_id = None
market_address = None
oracle_from_log = None
receipt_found = False

for log in receipt.get("logs", []):
    if str(log.get("address", "")).lower() != factory:
        continue
    topics = [str(topic).lower() for topic in log.get("topics", [])]
    if not topics or topics[0] != topic0:
        continue
    try:
        market_id = int(topics[1], 16)
    except Exception:
        market_id = None
    if len(topics) > 2:
        market_address = "0x" + topics[2][-40:]
    if len(topics) > 3:
        oracle_from_log = "0x" + topics[3][-40:]
    receipt_found = True
    break

expected_market_id = _as_int(os.environ.get("EXPECTED_MARKET_ID"))
predicted_address = os.environ.get("PREDICTED_ADDRESS", "")
if market_id is None:
    market_id = expected_market_id
if not market_address:
    market_address = predicted_address or None

predicted_match = False
if market_id is not None and expected_market_id is not None and market_address and predicted_address:
    predicted_match = market_id == expected_market_id and market_address.lower() == predicted_address.lower()

block_number = _as_int(receipt.get("blockNumber"))

payload = {
    "market_id": market_id,
    "market_address": market_address,
    "predicted_market_id": expected_market_id,
    "predicted_market_address": predicted_address or None,
    "predicted_match": predicted_match,
    "tx_hash": os.environ.get("TX_HASH"),
    "block_number": block_number,
    "factory_address": os.environ.get("FACTORY_ADDRESS"),
    "oracle": os.environ.get("ORACLE_ADDRESS"),
    "oracle_from_log": oracle_from_log,
    "verifier": os.environ.get("VERIFIER_ADDRESS"),
    "authorization_signer": os.environ.get("AUTHORIZATION_SIGNER"),
    "circuit_hash": os.environ.get("CIRCUIT_HASH"),
    "commit_deadline": _as_int(os.environ.get("COMMIT_DEADLINE")),
    "ticket_size_wei": _as_int(os.environ.get("TICKET_SIZE_WEI")),
    "max_commitments": _as_int(os.environ.get("MAX_COMMITMENTS")),
    "protocol_liability_cap_wei": _as_int(os.environ.get("PROTOCOL_LIABILITY_CAP_WEI")),
    "chain_id": _as_int(os.environ.get("CHAIN_ID")),
    "global_rake_bps": _as_int(os.environ.get("GLOBAL_RAKE_BPS")),
    "receipt_found": receipt_found,
}

output = json.dumps(payload, indent=2)
print(output)

output_path = os.environ.get("OUTPUT_PATH")
if output_path:
    Path(output_path).write_text(output)
PY

rm -f "${receipt_path}"
