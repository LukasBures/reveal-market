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

echo ""
echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
echo "!                   HAZARD — IRREVERSIBLE                    !"
echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
echo ""
echo "  This script will PERMANENTLY DELETE:"
echo ""
echo "    * All running and stopped containers"
echo "    * All Docker volumes  (database data, uploaded files, etc.)"
echo "    * All Docker images   (requires re-pulling / re-building)"
echo "    * All build cache     (next build will be a cold build)"
echo "    * All unused networks"
echo ""
echo "  There is NO undo. Data stored in volumes will be gone forever."
echo ""
echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
echo ""
read -r -p "Type 'yes' to confirm: " confirmation
if [[ "$confirmation" != "yes" ]]; then
  echo "Aborted." >&2
  exit 1
fi

PROD_HOSTNAME="reveal-market-prod"
COMPOSE_DIR="/home/reveal/apps/reveal-market"
BACKUP_DIR="/home/reveal/apps/reveal-market/db_backups"
PROJECT_NAME="reveal-market"
if [[ "$(hostname)" == "$PROD_HOSTNAME" ]]; then
  echo "Production server detected (hostname: $PROD_HOSTNAME)."
  echo "Backing up database to: $BACKUP_DIR before wipe..."

  POSTGRES_USER="market_admin"
  POSTGRES_DB="reveal_market"
  RETAIN_DAYS=14
  DATE=$(date -u +%Y-%m-%d-%H%M%S)
  DEST="${BACKUP_DIR}/${DATE}.dump.gz"

  # Derive PGPASSWORD from RM_DATABASE_URL in .env.production
  ENV_FILE="${COMPOSE_DIR}/.env.production"
  if [[ -z "${PGPASSWORD:-}" ]]; then
    if [[ -f "$ENV_FILE" ]]; then
      RM_DATABASE_URL_LINE=$(grep '^RM_DATABASE_URL=' "$ENV_FILE" | head -1 || true)
      if [[ -n "$RM_DATABASE_URL_LINE" ]]; then
        RM_DATABASE_URL_VALUE=${RM_DATABASE_URL_LINE#RM_DATABASE_URL=}
        PGPASSWORD=$(python3 - "$RM_DATABASE_URL_VALUE" << 'PYEOF' 2>/dev/null || true
import sys
from urllib.parse import urlparse
if len(sys.argv) < 2:
    sys.exit(1)
parsed = urlparse(sys.argv[1])
if parsed.password is None:
    sys.exit(1)
print(parsed.password)
PYEOF
)
      fi
    fi
  fi
  if [[ -z "${PGPASSWORD:-}" ]]; then
    echo "ERROR: PGPASSWORD not set and could not be derived from RM_DATABASE_URL in $ENV_FILE" >&2
    exit 1
  fi
  export PGPASSWORD

  mkdir -p "$BACKUP_DIR"
  echo "Writing backup to $DEST ..."
  POSTGRES_CONTAINER_ID=$(docker compose -f "${COMPOSE_DIR}/docker-compose.yml" ps -q postgres 2>/dev/null || true)
  if [[ -z "$POSTGRES_CONTAINER_ID" ]]; then
    echo "WARNING: postgres container is not running — cannot back up database." >&2
    read -r -p "Continue WITHOUT a backup? Type 'yes' to proceed: " skip_backup
    if [[ "$skip_backup" != "yes" ]]; then
      echo "Aborted. Start postgres first (docker compose up -d postgres) then re-run." >&2
      exit 1
    fi
    echo "Proceeding without backup."
  elif docker compose -f "${COMPOSE_DIR}/docker-compose.yml" \
      --env-file "$ENV_FILE" \
      exec -T postgres \
      pg_dump \
        --username="$POSTGRES_USER" \
        --dbname="$POSTGRES_DB" \
        --format=custom \
        --compress=0 \
    | gzip -9 > "$DEST"; then
    SIZE=$(du -sh "$DEST" | cut -f1)
    echo "Backup complete: $DEST ($SIZE)"
    # Prune backups older than RETAIN_DAYS days
    find "$BACKUP_DIR" -name "*.dump.gz" -mtime "+${RETAIN_DAYS}" -delete || true
  else
    echo "" >&2
    echo "ERROR: Database backup failed. Aborting wipe to protect data." >&2
    rm -f "$DEST"
    exit 1
  fi
  echo ""
else
  echo "Not on production server (hostname: $(hostname)). Skipping database backup."
  echo ""
fi

echo "Stopping running containers for project '${PROJECT_NAME}'..."
mapfile -t running_containers < <(docker ps -q --filter "label=com.docker.compose.project=${PROJECT_NAME}")
if (( ${#running_containers[@]} )); then
  docker stop "${running_containers[@]}"
else
  echo "No running containers for project '${PROJECT_NAME}'."
fi

echo "Removing all containers for project '${PROJECT_NAME}'..."
mapfile -t all_containers < <(docker ps -aq --filter "label=com.docker.compose.project=${PROJECT_NAME}")
if (( ${#all_containers[@]} )); then
  docker rm -f "${all_containers[@]}"
else
  echo "No containers to remove for project '${PROJECT_NAME}'."
fi

echo "Removing all volumes for project '${PROJECT_NAME}'..."
mapfile -t all_volumes < <(docker volume ls -q --filter "label=com.docker.compose.project=${PROJECT_NAME}")
if (( ${#all_volumes[@]} )); then
  docker volume rm -f "${all_volumes[@]}"
else
  echo "No volumes to remove for project '${PROJECT_NAME}'."
fi

echo "Pruning images, layers, volumes, and cache..."
docker system prune -a --volumes --force

echo "Docker environment wiped."
