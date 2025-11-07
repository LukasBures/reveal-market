#!/usr/bin/env bash
set -euo pipefail

# Build all containers from scratch (no cache) and bring the stack up.

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

"${COMPOSE_CMD[@]}" build --no-cache
"${COMPOSE_CMD[@]}" up "$@"
