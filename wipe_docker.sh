#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "docker command not found. Install Docker before running this script." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running. Start Docker before running this script." >&2
  exit 1
fi

echo "Docker context: $(docker context show 2>/dev/null || echo unknown)"
echo "Docker host: $(docker info --format 'ServerVersion={{.ServerVersion}} RootDir={{.DockerRootDir}} Name={{.Name}}' 2>/dev/null || echo unknown)"
echo "Host machine: $(hostname 2>/dev/null || echo unknown)"

echo "Stopping running containers..."
mapfile -t running_containers < <(docker ps -q)
if (( ${#running_containers[@]} )); then
  docker stop "${running_containers[@]}"
else
  echo "No running containers."
fi

echo "Removing all containers..."
mapfile -t all_containers < <(docker ps -aq)
if (( ${#all_containers[@]} )); then
  docker rm -f "${all_containers[@]}"
else
  echo "No containers to remove."
fi

echo "Removing all volumes..."
mapfile -t all_volumes < <(docker volume ls -q)
if (( ${#all_volumes[@]} )); then
  docker volume rm -f "${all_volumes[@]}"
else
  echo "No volumes to remove."
fi

echo "Pruning images, layers, volumes, and cache..."
docker system prune -a --volumes --force

echo "Docker environment wiped."
