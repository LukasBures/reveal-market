# Runbook: Database Restore

Use when the production database needs to be restored from a backup.

## Find available backups

```bash
aws s3 ls s3://${DB_BACKUP_BUCKET}/db/ | sort | tail -10
```

## Full restore from pg_dump backup

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

```bash
BACKUP_FILE="2026-03-07-020000.dump.gz"

aws s3 cp "s3://${DB_BACKUP_BUCKET}/db/${BACKUP_FILE}" - \
  | gunzip \
  | docker compose exec -T postgres \
      pg_restore \
        --host=localhost \
        --username=market_admin \
        --dbname=reveal_market \
        --no-owner \
        --no-privileges \
        --verbose
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
aws s3 cp "s3://${DB_BACKUP_BUCKET}/db/${BACKUP_FILE}" - \
  | gunzip \
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
aws s3 cp "s3://${DB_BACKUP_BUCKET}/db/${BACKUP_FILE}" /tmp/restore.dump.gz
gunzip /tmp/restore.dump.gz
pg_restore \
  --host=localhost \
  --username=market_admin \
  --dbname=reveal_market_debug \
  --no-owner \
  /tmp/restore.dump
```

## Test this runbook regularly

Run a test restore to a scratch database at least once per month. A backup that
has never been tested is not a reliable backup.

```bash
# Create scratch DB
createdb -U postgres reveal_market_test_restore

# Restore latest backup
aws s3 cp "$(aws s3 ls s3://${DB_BACKUP_BUCKET}/db/ | sort | tail -1 | awk '{print "s3://'${DB_BACKUP_BUCKET}'/db/"$4}')" - \
  | gunzip \
  | pg_restore --dbname=reveal_market_test_restore --no-owner

# Spot check
psql -d reveal_market_test_restore -c "SELECT COUNT(*) FROM markets;"
psql -d reveal_market_test_restore -c "SELECT COUNT(*) FROM commitments;"

# Clean up
dropdb reveal_market_test_restore
```
