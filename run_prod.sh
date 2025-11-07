#!/usr/bin/env bash
set -euo pipefail

# Build and launch the entire stack in detached mode (production target).

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

echo "Building Docker images..."
"${COMPOSE_CMD[@]}" build

echo "Starting services in detached mode..."
"${COMPOSE_CMD[@]}" up -d "$@"

"${COMPOSE_CMD[@]}" ps

echo "Deployment complete."
