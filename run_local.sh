#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# run_local.sh
# -----------------------------------------------------------------------------
# Full rebuild + launch script for developers.
# - Enables BuildKit + parallel builds (leaving one CPU free).
# - Forces a --no-cache compose build so every layer is fresh.
# - Starts docker compose in the foreground (logs stream to terminal).
#
# Usage: ./run_local.sh [extra docker-compose args]
#
# Examples:
#   ./run_local.sh
#   ./run_local.sh api worker   # Bring up subset of services after rebuild
# -----------------------------------------------------------------------------

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required to run the local stack" >&2
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

# Determine how many concurrent builds we can run (nproc - 1).
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

echo "Building images with --no-cache (parallel=${COMPOSE_PARALLEL_LIMIT})..."
"${COMPOSE_CMD[@]}" build --no-cache --parallel

echo "Starting services..."
"${COMPOSE_CMD[@]}" up "$@"
