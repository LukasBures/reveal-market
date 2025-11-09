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

# When developing locally we rarely have the API running, so default to the mock
# dataset unless the caller already exported either mock flag.
if [[ "${NEXT_PUBLIC_API_MOCK:-}" != "true" && "${RM_API_MOCK:-}" != "true" ]]; then
  echo "NOTE: NEXT_PUBLIC_API_MOCK/RM_API_MOCK not set; defaulting to mock API for build."
  export NEXT_PUBLIC_API_MOCK=true
  export RM_API_MOCK=true
fi

# Run lint before build to fail fast on lint errors. Build runs `next build`,
# which also validates types and static props.
npm run lint
npm run build

echo "Frontend lint + build completed."
