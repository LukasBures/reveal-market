#!/usr/bin/env bash
# Smoke-test the frontend (lint + production build). Mirrors CI behavior so we
# catch TypeScript/Next regressions locally before pushing.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to run frontend tests." >&2
  exit 1
fi

cd "${PROJECT_DIR}"

# Require the backend API to be reachable so SSR/SSG calls succeed.
API_BASE="${NEXT_PUBLIC_API_BASE_URL:-http://localhost:8000}"
if ! curl -fsS "${API_BASE%/}/health" >/dev/null 2>&1; then
  echo "Frontend requires the API at ${API_BASE}; make sure the backend stack is running." >&2
  exit 1
fi
export RM_API_BASE_URL="${RM_API_BASE_URL:-${API_BASE}}"

# Run lint before build to fail fast on lint errors. Build runs `next build`,
# which also validates types and static props.
npm run lint
npm run build

echo "Frontend lint + build completed."
