#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# run_local.sh
# -----------------------------------------------------------------------------
# Full rebuild + launch script for developers.
# - Enables BuildKit + parallel builds (leaving one CPU free).
# - Defaults to a --no-cache compose build so every layer is fresh (use --cache to reuse layers).
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

# Determine how many concurrent builds we can run (nproc - 1).
# Keeps at least one CPU free so the host stays responsive.
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

# Enable BuildKit + Compose's CLI mode so builds are faster and parallelizable.
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
export COMPOSE_PARALLEL_LIMIT="${PARALLEL_BUILDS}"

BUILD_FLAG="--no-cache"
UP_ARGS=()

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
    --help|-h)
      echo "Usage: ./run_local.sh [--cache|--no-cache] [compose up args...]"
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

BUILD_DESC="${BUILD_FLAG:-cached layers}"
echo "Building images (${BUILD_DESC}, parallel=${COMPOSE_PARALLEL_LIMIT})..."
if [[ -n "${BUILD_FLAG}" ]]; then
  "${COMPOSE_CMD[@]}" build "${BUILD_FLAG}" --parallel
else
  "${COMPOSE_CMD[@]}" build --parallel
fi

echo "Starting services..."
"${COMPOSE_CMD[@]}" up "${UP_ARGS[@]}"
