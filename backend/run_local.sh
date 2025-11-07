#!/usr/bin/env bash
set -euo pipefail

# Run the local backend stack (API, worker, Postgres, Redis) via docker compose.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v docker &>/dev/null; then
  echo "docker is required to run the local backend stack" >&2
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

(
  cd "${ROOT_DIR}"
  "${COMPOSE_CMD[@]}" up --build
)
