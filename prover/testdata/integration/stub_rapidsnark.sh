#!/usr/bin/env bash
set -euo pipefail

# Arguments: <zkey> <witness> <proof.json> <public.json>
PROOF_FILE="$3"
PUBLIC_FILE="$4"

cat <<'JSON' > "$PROOF_FILE"
{
  "pi_a": ["1", "2"],
  "pi_b": [
    ["3", "4"],
    ["5", "6"]
  ],
  "pi_c": ["7", "8"]
}
JSON

echo '["9","10"]' > "$PUBLIC_FILE"
