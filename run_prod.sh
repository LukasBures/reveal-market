#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# run_prod.sh
# -----------------------------------------------------------------------------
# Production-friendly deploy helper.
# - Builds images with cache (faster) using BuildKit + limited parallelism.
# - Runs docker compose up -d so containers stay in the background.
# - Prints docker compose ps at the end for quick status.
#
# Usage: ./run_prod.sh [extra docker-compose args]
# -----------------------------------------------------------------------------

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required to deploy the stack" >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=("docker" "compose")
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=("docker-compose")
else
  echo "docker compose or docker-compose is required" >&2
  exit 1
fi

cd "${ROOT_DIR}"

if command -v nproc >/dev/null 2>&1; then
  PARALLEL_BUILDS="$(nproc --ignore=1)"
elif [[ "$(uname -s)" == "Darwin" ]]; then
  PARALLEL_BUILDS="$(/usr/sbin/sysctl -n hw.ncpu 2>/dev/null || echo 2)"
else
  PARALLEL_BUILDS=2
fi
if [[ -z "${PARALLEL_BUILDS}" || "${PARALLEL_BUILDS}" -lt 1 ]]; then
  PARALLEL_BUILDS=1
fi

export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
export COMPOSE_PARALLEL_LIMIT="${PARALLEL_BUILDS}"

echo "Building Docker images (cached)..."
"${COMPOSE_CMD[@]}" build --parallel

echo "Starting services in detached mode..."
"${COMPOSE_CMD[@]}" up -d "$@"

"${COMPOSE_CMD[@]}" ps

echo "Deployment complete."
