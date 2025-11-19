#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "docker command not found. Install Docker before running this script." >&2
  exit 1
fi

echo "Stopping running containers..."
running_containers=$(docker ps -q)
if [[ -n "${running_containers}" ]]; then
  docker stop ${running_containers}
else
  echo "No running containers."
fi

echo "Removing all containers..."
all_containers=$(docker ps -aq)
if [[ -n "${all_containers}" ]]; then
  docker rm -f ${all_containers}
else
  echo "No containers to remove."
fi

echo "Pruning images, layers, volumes, and cache..."
docker system prune -a --volumes --force

echo "Docker environment wiped."
