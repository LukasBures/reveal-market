#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# run_local.sh
# -----------------------------------------------------------------------------
# Full rebuild + launch script for developers.
# - Enables BuildKit + parallel builds (leaving one CPU free).
# - Defaults to a --no-cache + --pull compose build so every layer is fresh (use --cache to reuse layers).
# - Optional --skip-build for faster iterations when only restarting containers.
# - Starts docker compose (with --remove-orphans) in the foreground so logs stream to the terminal.
# - Tip: run `make test` (backend) / `npm run test` (frontend) before calling this to catch errors earlier.
#
# Usage: ./run_local.sh [extra docker-compose args]
#
# Examples:
#   ./run_local.sh
#   ./run_local.sh api worker   # Bring up subset of services after rebuild
# -----------------------------------------------------------------------------

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Sanity-check that Docker is installed.
if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required to run the local stack" >&2
  exit 1
fi

# Compose v2 (docker compose) is preferred; fall back to classic docker-compose.
if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=("docker" "compose")
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=("docker-compose")
else
  echo "docker compose or docker-compose is required" >&2
  exit 1
fi

cd "${ROOT_DIR}"

calc_parallel_builds() {
  # Compose refuses to parallelise more builds than CPUs, so detect the host
  # count once and leave one core idle to keep laptops responsive.
  local cpus
  if command -v nproc >/dev/null 2>&1; then
    cpus="$(nproc 2>/dev/null || echo 1)"
  elif [[ "$(uname -s)" == "Darwin" ]]; then
    cpus="$(/usr/sbin/sysctl -n hw.ncpu 2>/dev/null || echo 1)"
  else
    cpus=1
  fi
  if [[ -z "${cpus}" || "${cpus}" -lt 2 ]]; then
    echo 1
  else
    echo $((cpus - 1))
  fi
}

PARALLEL_BUILDS="$(calc_parallel_builds)"

# Enable BuildKit + Compose's CLI mode so builds are faster and parallelizable.
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
export COMPOSE_PARALLEL_LIMIT="${PARALLEL_BUILDS}"

BUILD_FLAG="--no-cache"
RUN_BUILD="true"
UP_ARGS=()

usage() {
  cat <<EOF
Usage: ./run_local.sh [--cache|--no-cache] [--skip-build] [compose up args...]
  --cache        Reuse existing build layers.
  --no-cache     Force a clean rebuild (default).
  --skip-build   Skip the docker compose build step entirely.
  -h, --help     Show this help text.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cache)
      BUILD_FLAG=""
      shift
      ;;
    --no-cache)
      BUILD_FLAG="--no-cache"
      shift
      ;;
    --skip-build)
      RUN_BUILD="false"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      UP_ARGS+=("$@")
      break
      ;;
    *)
      UP_ARGS+=("$1")
      shift
      ;;
  esac
done

echo "Validating docker compose files..."
"${COMPOSE_CMD[@]}" config >/dev/null
if [[ "${RUN_BUILD}" == "true" ]]; then
  BUILD_DESC="${BUILD_FLAG:-cached layers}"
  echo "Building images (${BUILD_DESC}, pull latest bases, parallel=${COMPOSE_PARALLEL_LIMIT})..."
  BUILD_OPTS=(--parallel --pull)
  if [[ -n "${BUILD_FLAG}" ]]; then
    BUILD_OPTS+=("${BUILD_FLAG}")
  fi
  "${COMPOSE_CMD[@]}" build "${BUILD_OPTS[@]}"
else
  echo "Skipping docker compose build step (per --skip-build)."
fi

echo "Starting services..."
UP_CMD=("${COMPOSE_CMD[@]}" up "--remove-orphans" "--detach")
if [[ ${#UP_ARGS[@]} -gt 0 ]]; then
  UP_CMD+=("${UP_ARGS[@]}")
fi
"${UP_CMD[@]}"

API_PORT="${API_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
POSTGRES_URI="${POSTGRES_URI:-postgres://market_admin:<REDACTED>@localhost:5432/reveal_market}"
REDIS_CMD="${REDIS_CMD:-redis-cli -h localhost -p 6379}"

cat <<EOF
------------------------------------------------------------
Stack ready. Useful URLs while running locally:
  • API docs / health:      http://localhost:${API_PORT}/docs  | http://localhost:${API_PORT}/health
  • Frontend / marketing:   http://localhost:${FRONTEND_PORT}/
  • Postgres (psql):        ${POSTGRES_URI}
  • Redis (CLI):            ${REDIS_CMD}
------------------------------------------------------------
📜 Logs will follow (Ctrl+C to stop):
------------------------------------------------------------
EOF

LOG_TARGETS=("${UP_ARGS[@]}")
"${COMPOSE_CMD[@]}" logs -f "${LOG_TARGETS[@]}"
