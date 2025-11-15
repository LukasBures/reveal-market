#!/usr/bin/env bash
set -euo pipefail

# Arguments: <script> <wasm> <input.json> <output.wtns>
INPUT_FILE="$3"
OUTPUT_FILE="$4"

if [[ ! -f "$INPUT_FILE" ]]; then
  echo "input missing" >&2
  exit 1
fi

echo "stub-witness:$(cat "$INPUT_FILE")" > "$OUTPUT_FILE"
