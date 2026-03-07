#!/usr/bin/env bash
# Item 6: Daily database backup to S3-compatible object storage.
#
# Usage (manual):
#   DB_BACKUP_BUCKET=your-bucket ./scripts/backup_db.sh
#
# Cron (add to prod server crontab as the deploy user):
#   0 2 * * * /opt/reveal-market/scripts/backup_db.sh >> /var/log/db-backup.log 2>&1
#
# Required env vars:
#   DB_BACKUP_BUCKET       — S3 bucket name (no trailing slash, no s3:// prefix)
#   POSTGRES_HOST          — defaults to localhost
#   POSTGRES_PORT          — defaults to 5432
#   POSTGRES_USER          — defaults to market_admin
#   POSTGRES_DB            — defaults to reveal_market
#   PGPASSWORD             — Postgres password (or use .pgpass)
#
# Optional env vars:
#   DB_BACKUP_RETAIN_DAYS  — number of daily backups to keep (default: 30)
#   AWS_PROFILE            — AWS profile to use (if not using instance role)
#
# The backup is a gzip-compressed pg_dump in custom format for fast selective
# restore. Verify the restore procedure works before relying on this in prod.

set -euo pipefail

BUCKET="${DB_BACKUP_BUCKET:?DB_BACKUP_BUCKET env var is required}"
HOST="${POSTGRES_HOST:-localhost}"
PORT="${POSTGRES_PORT:-5432}"
USER="${POSTGRES_USER:-market_admin}"
DB="${POSTGRES_DB:-reveal_market}"
RETAIN_DAYS="${DB_BACKUP_RETAIN_DAYS:-30}"
DATE=$(date -u +%Y-%m-%d-%H%M%S)
DEST="s3://${BUCKET}/db/${DATE}.dump.gz"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting backup of ${DB}@${HOST}:${PORT} → ${DEST}"

pg_dump \
  --host="${HOST}" \
  --port="${PORT}" \
  --username="${USER}" \
  --dbname="${DB}" \
  --no-password \
  --format=custom \
  --compress=0 \
  | gzip -9 \
  | aws s3 cp - "${DEST}" \
      --storage-class STANDARD_IA \
      --expected-size 1

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Backup complete: ${DEST}"

# Prune backups older than RETAIN_DAYS
CUTOFF=$(date -u -d "${RETAIN_DAYS} days ago" +%Y-%m-%d 2>/dev/null \
         || date -u -v "-${RETAIN_DAYS}d" +%Y-%m-%d 2>/dev/null \
         || echo "")

if [ -n "${CUTOFF}" ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Pruning backups older than ${CUTOFF} (retain ${RETAIN_DAYS} days)..."
  aws s3 ls "s3://${BUCKET}/db/" \
    | awk '{print $4}' \
    | grep '\.dump\.gz$' \
    | while read -r key; do
        FILE_DATE=$(echo "${key}" | cut -c1-10)
        if [ "${FILE_DATE}" \< "${CUTOFF}" ]; then
          echo "  Deleting s3://${BUCKET}/db/${key}"
          aws s3 rm "s3://${BUCKET}/db/${key}"
        fi
      done
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Pruning complete."
fi
