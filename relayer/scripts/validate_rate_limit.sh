#!/usr/bin/env bash
set -euo pipefail

# Smoke test rate limiting against /commit using an expired payload.

BASE_URL="${RELAYER_BASE_URL:-http://${RELAYER_HOST:-127.0.0.1}:${RELAYER_PORT:-8088}}"
RATE_LIMIT_REQUESTS="${RELAYER_RATE_LIMIT_REQUESTS:-30}"

if [[ "${RELAYER_ALLOW_INSECURE_AUTH:-false}" != "true" && -z "${RELAYER_BEARER_TOKEN:-}" ]]; then
  echo "RELAYER_BEARER_TOKEN is required unless RELAYER_ALLOW_INSECURE_AUTH=true" >&2
  exit 1
fi

if [[ "${RATE_LIMIT_REQUESTS}" == "0" ]]; then
  echo "RELAYER_RATE_LIMIT_REQUESTS=0 disables rate limiting; nothing to validate." >&2
  exit 1
fi

if ! [[ "${RATE_LIMIT_REQUESTS}" =~ ^[0-9]+$ ]]; then
  echo "RELAYER_RATE_LIMIT_REQUESTS must be an integer" >&2
  exit 1
fi

AUTH_ARGS=()
if [[ -n "${RELAYER_BEARER_TOKEN:-}" ]]; then
  AUTH_ARGS=(-H "Authorization: Bearer ${RELAYER_BEARER_TOKEN}")
fi

payload='{"user":"0x0000000000000000000000000000000000000001","market":"0x0000000000000000000000000000000000000002","commitment":"0x0000000000000000000000000000000000000000000000000000000000000000","nonce":1,"expiry":1,"chain_id":1,"ticket_value_wei":1,"signature":"0x1111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111"}'

echo "Validating rate limit at ${BASE_URL}/commit with ${RATE_LIMIT_REQUESTS}+1 requests"

for ((i = 1; i <= RATE_LIMIT_REQUESTS; i++)); do
  status="$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Content-Type: application/json" \
    "${AUTH_ARGS[@]}" \
    -d "${payload}" \
    "${BASE_URL}/commit")"
  if [[ "${status}" == "429" ]]; then
    echo "Unexpected 429 at request ${i}/${RATE_LIMIT_REQUESTS}" >&2
    exit 1
  fi
done

status="$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Content-Type: application/json" \
  "${AUTH_ARGS[@]}" \
  -d "${payload}" \
  "${BASE_URL}/commit")"

if [[ "${status}" != "429" ]]; then
  echo "Expected 429 on request $((RATE_LIMIT_REQUESTS + 1)), got ${status}" >&2
  exit 1
fi

echo "Rate limit OK (received 429 after ${RATE_LIMIT_REQUESTS} requests)."
