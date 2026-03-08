#!/usr/bin/env bash
# prod_db_backups/pull_backup.sh
# Download a database backup from the production server to this directory.
#
# Usage:
#   ./prod_db_backups/pull_backup.sh                              # downloads latest
#   ./prod_db_backups/pull_backup.sh 2026-03-08-020000.dump.gz   # specific file
#
# Requires: ssh alias "reveal-market-prod" configured in ~/.ssh/config

set -euo pipefail

REMOTE="reveal-market-prod"
REMOTE_DIR="/var/backups/reveal-market"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
SPECIFIC_FILE="${1:-}"

if [ -n "${SPECIFIC_FILE}" ]; then
    echo "Downloading ${SPECIFIC_FILE} from ${REMOTE}..."
    rsync -avz --progress \
        "${REMOTE}:${REMOTE_DIR}/${SPECIFIC_FILE}" \
        "${LOCAL_DIR}/"
    echo "Saved to ${LOCAL_DIR}/${SPECIFIC_FILE}"
else
    echo "Finding latest backup on ${REMOTE}..."
    LATEST=$(ssh "${REMOTE}" "ls -1t ${REMOTE_DIR}/*.dump.gz 2>/dev/null | head -1" || echo "")
    if [ -z "${LATEST}" ]; then
        echo "No backups found at ${REMOTE}:${REMOTE_DIR}" >&2
        echo "Run 'ssh ${REMOTE} /opt/reveal-market/scripts/backup_db.sh' to create one." >&2
        exit 1
    fi
    FILENAME=$(basename "${LATEST}")
    echo "Latest: ${FILENAME}"
    rsync -avz --progress \
        "${REMOTE}:${LATEST}" \
        "${LOCAL_DIR}/"
    echo "Saved to ${LOCAL_DIR}/${FILENAME}"
fi
