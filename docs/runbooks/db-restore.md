# Runbook: Database Restore

Use when the production database needs to be restored from a backup.

Backups are stored on the production server at `/var/backups/reveal-market/` and rotated
after 14 days. The cron job runs daily at 02:00 UTC.

## Find available backups

```bash
# On the production server
ssh reveal-market-prod "ls -lht /var/backups/reveal-market/ | head -10"
```

## Pull a backup to your local machine

```bash
# Pull latest
./prod_db_backups/pull_backup.sh

# Pull a specific file
./prod_db_backups/pull_backup.sh 2026-03-08-020000.dump.gz
```

## Full restore from backup

### 1. Stop services that write to the database

```bash
docker compose -f docker-compose.yml --env-file .env.production \
  stop api worker relayer hedger
```

### 2. Drop and recreate the database (if needed)

```bash
docker compose exec postgres psql -U postgres -c "DROP DATABASE IF EXISTS reveal_market;"
docker compose exec postgres psql -U postgres -c "CREATE DATABASE reveal_market OWNER market_admin;"
```

### 3. Restore from the chosen backup

Copy the backup to the server (or run directly on the server if the file is already there):

```bash
BACKUP_FILE="2026-03-08-020000.dump.gz"

# Restore from local file
gunzip -c "prod_db_backups/${BACKUP_FILE}" \
  | docker compose exec -T postgres \
      pg_restore \
        --username=market_admin \
        --dbname=reveal_market \
        --no-owner \
        --no-privileges \
        --verbose

# Restore directly on the server (no local download needed)
ssh reveal-market-prod "
  gunzip -c /var/backups/reveal-market/${BACKUP_FILE} \
    | docker compose -f /opt/reveal-market/docker-compose.yml exec -T postgres \
        pg_restore --username=market_admin --dbname=reveal_market --no-owner --no-privileges
"
```

### 4. Run migrations to bring schema up to date (if restore is from older backup)

```bash
cd backend/migrations
uv run --project ../api --extra dev alembic upgrade head
```

### 5. Restart all services

```bash
docker compose -f docker-compose.yml --env-file .env.production \
  up -d api worker relayer hedger
```

### 6. Verify

```bash
# Check API health
curl -sf https://api.revealmarket.xyz/healthz | jq .

# Spot-check data
curl -sf https://api.revealmarket.xyz/markets?limit=5 | jq '.[].id'
```

## Partial restore (single table)

To restore only a specific table without touching the rest:

```bash
gunzip -c "prod_db_backups/${BACKUP_FILE}" \
  | docker compose exec -T postgres \
      pg_restore \
        --username=market_admin \
        --dbname=reveal_market \
        --table=commitments \
        --no-owner \
        --data-only
```

## Restore to a local environment for investigation

```bash
# Pull the backup
./prod_db_backups/pull_backup.sh

# Restore into a local scratch database
gunzip -c "prod_db_backups/${BACKUP_FILE}" \
  | pg_restore \
      --host=localhost \
      --username=market_admin \
      --dbname=reveal_market_debug \
      --no-owner
```

## Test this runbook regularly

Run a test restore to a scratch database at least once per month. A backup that
has never been tested is not a reliable backup.

```bash
# Pull latest backup locally
./prod_db_backups/pull_backup.sh

# Create scratch DB (adjust host/port for your local setup)
createdb -h localhost -p 15432 -U market_admin reveal_market_test_restore

# Restore
gunzip -c prod_db_backups/*.dump.gz | tail -1 \
  | pg_restore \
      --host=localhost \
      --port=15432 \
      --username=market_admin \
      --dbname=reveal_market_test_restore \
      --no-owner

# Spot check
psql -h localhost -p 15432 -U market_admin -d reveal_market_test_restore \
  -c "SELECT COUNT(*) FROM markets;"
psql -h localhost -p 15432 -U market_admin -d reveal_market_test_restore \
  -c "SELECT COUNT(*) FROM commitments;"

# Clean up
dropdb -h localhost -p 15432 -U market_admin reveal_market_test_restore
```

## Trigger a manual backup on the server

```bash
ssh reveal-market-prod "/opt/reveal-market/scripts/backup_db.sh"
```
