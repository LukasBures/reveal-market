#!/usr/bin/env bash
# Smoke-test the frontend (lint + production build).

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to run frontend tests." >&2
  exit 1
fi

cd "${PROJECT_DIR}"
npm run lint
npm run build

echo "Frontend lint + build completed."
