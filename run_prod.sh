#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# run_prod.sh
# -----------------------------------------------------------------------------
# Production-friendly deploy helper.
# - Builds images with cache (faster) using BuildKit + limited parallelism and always pulls base layers.
# - Optional --skip-build flag for already-built deployments.
# - Runs docker compose up -d --remove-orphans (and --wait when supported) so containers stay in the background.
# - Prints docker compose ps at the end for quick status.
# - Reminder: run CI-equivalent tests (make test / contracts/run_local.sh full / npm run build) before deploying.
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

calc_parallel_builds() {
  # Server SKUs vary wildly; detect available CPUs once and hold one core back so
  # docker build logs remain readable under load.
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

supports_wait_flag() {
  # Newer docker compose releases support --wait to block until healthchecks
  # succeed. Detect support dynamically so older hosts continue to work.
  if "${COMPOSE_CMD[@]}" up --help 2>&1 | grep -q -- "--wait"; then
    return 0
  fi
  return 1
}

PARALLEL_BUILDS="$(calc_parallel_builds)"
WAIT_FLAG=()
if supports_wait_flag; then
  WAIT_FLAG+=("--wait")
fi

export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
export COMPOSE_PARALLEL_LIMIT="${PARALLEL_BUILDS}"

RUN_BUILD="true"
UP_ARGS=()

usage() {
  cat <<EOF
Usage: ./run_prod.sh [--skip-build] [compose up args...]
  --skip-build   Skip the docker compose build step (useful when images are already built/pulled).
  -h, --help     Show this help text.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
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
  echo "Building Docker images (cached layers, pulling latest bases, parallel=${COMPOSE_PARALLEL_LIMIT})..."
  "${COMPOSE_CMD[@]}" build --parallel --pull
else
  echo "Skipping docker compose build step (per --skip-build)."
fi

echo "Starting services in detached mode..."
UP_CMD=("${COMPOSE_CMD[@]}" up "-d" "--remove-orphans" "${WAIT_FLAG[@]}")
if [[ ${#UP_ARGS[@]} -gt 0 ]]; then
  UP_CMD+=("${UP_ARGS[@]}")
fi
"${UP_CMD[@]}"

"${COMPOSE_CMD[@]}" ps

echo "Deployment complete."
