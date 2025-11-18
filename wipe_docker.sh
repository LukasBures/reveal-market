#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "docker command not found. Install Docker before running this script." >&2
  exit 1
fi

echo "Stopping running containers..."
if [ -n "$(docker ps -q)" ]; then
  docker stop "$(docker ps -q)"
else
  echo "No running containers."
fi

echo "Removing all containers..."
if [ -n "$(docker ps -aq)" ]; then
  docker rm -f "$(docker ps -aq)"
else
  echo "No containers to remove."
fi

echo "Pruning images, layers, volumes, and cache..."
docker system prune -a --volumes --force

echo "Docker environment wiped."
