#!/usr/bin/env bash
# scripts/backup_db_local.sh
# Daily PostgreSQL backup to local disk on the production server.
#
# Deploy this file to the production server:
#   scp scripts/backup_db_local.sh reveal-market-prod:/opt/reveal-market/scripts/backup_db.sh
#   ssh reveal-market-prod "chmod +x /opt/reveal-market/scripts/backup_db.sh"
#
# Cron (as reveal user — 02:00 UTC daily):
#   0 2 * * * /opt/reveal-market/scripts/backup_db.sh >> /var/log/db-backup.log 2>&1
#
# Env vars (all optional — defaults shown):
#   COMPOSE_DIR          /opt/reveal-market   (directory containing docker-compose.yml)
#   POSTGRES_USER        market_admin
#   POSTGRES_DB          reveal_market
#   PGPASSWORD           auto-derived from RM_DATABASE_URL in .env.production if not set
#   BACKUP_DIR           /var/backups/reveal-market
#   BACKUP_RETAIN_DAYS   14

set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/opt/reveal-market}"
POSTGRES_USER="${POSTGRES_USER:-market_admin}"
POSTGRES_DB="${POSTGRES_DB:-reveal_market}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/reveal-market}"
RETAIN_DAYS="${BACKUP_RETAIN_DAYS:-14}"
DATE=$(date -u +%Y-%m-%d-%H%M%S)
DEST="${BACKUP_DIR}/${DATE}.dump.gz"
LOG_PREFIX="[$(date -u +%Y-%m-%dT%H:%M:%SZ)]"

# Derive PGPASSWORD from RM_DATABASE_URL in .env.production if not already set.
# Expected format: postgresql+psycopg2://user:<REDACTED>@host:port/db
if [ -z "${PGPASSWORD:-}" ]; then
    ENV_FILE="${COMPOSE_DIR}/.env.production"
    if [ -f "${ENV_FILE}" ]; then
        PGPASSWORD=$(grep '^RM_DATABASE_URL=' "${ENV_FILE}" \
            | sed 's|.*://[^:]*:\([^@]*\)@.*|\1|' \
            | head -1)
    fi
fi

if [ -z "${PGPASSWORD:-}" ]; then
    echo "${LOG_PREFIX} ERROR: PGPASSWORD not set and could not be derived from RM_DATABASE_URL in ${COMPOSE_DIR}/.env.production" >&2
    exit 1
fi
export PGPASSWORD

echo "${LOG_PREFIX} Starting backup of ${POSTGRES_DB} → ${DEST}"

mkdir -p "${BACKUP_DIR}"

# -T disables pseudo-TTY (required when piping binary pg_dump output through gzip)
# --env-file is required so compose can interpolate all service variables
docker compose -f "${COMPOSE_DIR}/docker-compose.yml" \
    --env-file "${COMPOSE_DIR}/.env.production" \
    exec -T postgres \
    pg_dump \
        --username="${POSTGRES_USER}" \
        --dbname="${POSTGRES_DB}" \
        --format=custom \
        --compress=0 \
    | gzip -9 > "${DEST}"

SIZE=$(du -sh "${DEST}" | cut -f1)
echo "${LOG_PREFIX} Backup complete: ${DEST} (${SIZE})"

# Prune backups older than RETAIN_DAYS
echo "${LOG_PREFIX} Pruning backups older than ${RETAIN_DAYS} days..."
find "${BACKUP_DIR}" -name "*.dump.gz" -mtime "+${RETAIN_DAYS}" -print -delete \
    | sed 's/^/  Deleted: /' || true
echo "${LOG_PREFIX} Done."
