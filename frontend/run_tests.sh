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

# Load repo-root .env so NEXT_PUBLIC_* variables (WalletConnect, etc.) are
# available without duplicating files under frontend/.
ROOT_ENV="${PROJECT_DIR}/../.env"
if [[ -f "${ROOT_ENV}" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "${ROOT_ENV}"
  set +a
fi

# Try to reach the backend API but continue in "offline" mode when it is
# unavailable. Offline mode points both server + browser env vars at an
# unroutable loopback address so fetch() calls fail fast without needing the
# Docker stack.
DEFAULT_API_BASE="${RM_API_BASE_URL:-${NEXT_PUBLIC_API_BASE_URL:-http://localhost:8000}}"
CHECK_URL="${DEFAULT_API_BASE%/}/health"
OFFLINE_API_BASE="http://127.0.0.1:65535"
API_TIMEOUT="${FRONTEND_API_CHECK_TIMEOUT:-2}"

if curl -fsS --max-time "${API_TIMEOUT}" "${CHECK_URL}" >/dev/null 2>&1; then
  echo "Frontend API reachable at ${CHECK_URL}"
  export RM_API_BASE_URL="${RM_API_BASE_URL:-${DEFAULT_API_BASE}}"
  export NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-${DEFAULT_API_BASE}}"
else
  echo "Frontend API ${CHECK_URL} is unreachable; running tests in offline mode."
  echo "Requests will target ${OFFLINE_API_BASE} so fetch() short-circuits locally."
  export RM_API_BASE_URL="${OFFLINE_API_BASE}"
  export NEXT_PUBLIC_API_BASE_URL="${OFFLINE_API_BASE}"
fi

# Run lint before build to fail fast on lint errors. Build runs `next build`,
# which also validates types and static props.
npm run lint
npm run build

echo "Frontend lint + build completed."
