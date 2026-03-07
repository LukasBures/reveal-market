#!/usr/bin/env bash
# Item 9: Verify internal service ports are not reachable from the public internet.
#
# Usage:
#   ./scripts/verify_firewall.sh <server-ip>
#
# Run this from any machine OUTSIDE the server (laptop, CI runner, separate VPS).
# All tested ports must be blocked — if any port is reachable the script exits non-zero.
#
# Ports checked:
#   8085  prover
#   8088  relayer
#   8090  hedger admin
#   8100  streamer
#   9090  prometheus
#   9187  postgres-exporter
#   9121  redis-exporter
#   5432  postgres
#   6379  redis
#
# Note: Docker's iptables DOCKER chain can bypass ufw INPUT rules. Use cloud-level
# security groups (AWS SG, GCP Firewall, Hetzner Firewall) — not just ufw — to
# guarantee these ports are blocked at the network edge.

set -euo pipefail

SERVER="${1:-}"
if [ -z "$SERVER" ]; then
  echo "Usage: $0 <server-ip-or-hostname>" >&2
  exit 1
fi

BLOCKED_PORTS=(8085 8088 8090 8100 9090 9187 9121 5432 6379)
TIMEOUT=3
EXIT_CODE=0

echo "Checking blocked ports on ${SERVER} (timeout ${TIMEOUT}s per port)..."
echo ""

for port in "${BLOCKED_PORTS[@]}"; do
  if nc -z -w"${TIMEOUT}" "${SERVER}" "${port}" 2>/dev/null; then
    echo "  FAIL  port ${port} is REACHABLE from outside — must be blocked"
    EXIT_CODE=1
  else
    echo "  OK    port ${port} is blocked"
  fi
done

echo ""
if [ "${EXIT_CODE}" -eq 0 ]; then
  echo "All internal ports are correctly blocked."
else
  echo "One or more internal ports are publicly reachable."
  echo "Use cloud-level security group rules (not just ufw) to block them."
fi

exit "${EXIT_CODE}"
