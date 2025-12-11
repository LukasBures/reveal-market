#!/usr/bin/env bash
# Smoke-test the frontend (lint + production build). Mirrors CI behavior so we
# catch TypeScript/Next regressions locally before pushing.

set -euo pipefail

timestamp() {
  date +"%Y-%m-%d %H:%M:%S"
}

log_step() {
  printf '\n[%s] >>> %s\n' "$(timestamp)" "$*"
}

log_warn() {
  printf '[%s] WARN: %s\n' "$(timestamp)" "$*" >&2
}

log_error() {
  printf '[%s] ERROR: %s\n' "$(timestamp)" "$*" >&2
}

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v npm >/dev/null 2>&1; then
  log_error "npm is required to run frontend tests."
  exit 1
fi

cd "${PROJECT_DIR}"

# Load repo-root .env so NEXT_PUBLIC_* variables propagate.
ROOT_ENV="${PROJECT_DIR}/../.env"
ROOT_ENV_LOCAL="${PROJECT_DIR}/../.env.local"
ROOT_ENV_PROD="${PROJECT_DIR}/../.env.prod"
if [[ -f "${ROOT_ENV}" ]]; then
  log_step "Loading environment from ${ROOT_ENV}"
  # shellcheck disable=SC1090
  set -a
  source "${ROOT_ENV}"
  set +a
elif [[ -f "${ROOT_ENV_LOCAL}" ]]; then
  log_warn ".env not found; falling back to ${ROOT_ENV_LOCAL}"
  # shellcheck disable=SC1090
  set -a
  source "${ROOT_ENV_LOCAL}"
  set +a
elif [[ -f "${ROOT_ENV_PROD}" ]]; then
  log_warn ".env/.env.local not found; falling back to ${ROOT_ENV_PROD}"
  set -a
  # shellcheck disable=SC1090
  source "${ROOT_ENV_PROD}"
  set +a
else
  log_warn "No env file (.env, .env.local, or .env.prod) found; using current environment."
fi

# Try to reach the backend API; warn if unreachable but proceed by default so
# local runs can still build against the configured host (override with FRONTEND_REQUIRE_API=true).
MODE_ENV="${MODE:-${NODE_ENV:-development}}"
if [[ "${MODE_ENV,,}" == *prod* ]]; then
  DEFAULT_API_BASE="${RM_API_BASE_URL:-https://api.revealmarket.xyz}"
else
  DEFAULT_API_BASE="${RM_API_BASE_URL:-http://localhost:8000}"
fi
CHECK_URL="${DEFAULT_API_BASE%/}/health"
API_TIMEOUT="${FRONTEND_API_CHECK_TIMEOUT:-2}"
STRICT_API_CHECK="${FRONTEND_REQUIRE_API:-false}"

if curl -fsS --max-time "${API_TIMEOUT}" "${CHECK_URL}" >/dev/null 2>&1; then
  log_step "Frontend API reachable at ${CHECK_URL}"
else
  if [[ "${STRICT_API_CHECK}" == "true" ]]; then
    log_error "Frontend API ${CHECK_URL} is unreachable. Start the backend stack (./run_local.sh) before running frontend tests."
    exit 1
  fi
  log_warn "Frontend API ${CHECK_URL} is unreachable; continuing with the configured base URL."
fi

export RM_API_BASE_URL="${RM_API_BASE_URL:-${DEFAULT_API_BASE}}"

# Run lint before build to fail fast on lint errors.
log_step "Running frontend lint"
npm run lint

log_step "Running frontend build"
npm run build

log_step "Frontend lint + build completed successfully"
