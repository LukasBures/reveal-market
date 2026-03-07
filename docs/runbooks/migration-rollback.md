# Runbook: Database Migration Rollback

Use when a schema migration causes unexpected errors or data issues in production.

## Before every migration in production

```bash
# ALWAYS take a backup before migrating
DB_BACKUP_BUCKET=your-bucket ./scripts/backup_db.sh
```

Confirm the backup exists:

```bash
aws s3 ls s3://your-bucket/db/ | tail -5
```

## Check current revision

```bash
cd backend/migrations
uv run --project ../api --extra dev alembic current
```

## Roll back one step

```bash
cd backend/migrations
uv run --project ../api --extra dev alembic downgrade -1
```

Verify:

```bash
uv run --project ../api --extra dev alembic current
```

## Roll back to a specific revision

Find the target revision ID:

```bash
uv run --project ../api --extra dev alembic history --verbose | head -40
```

Then downgrade:

```bash
uv run --project ../api --extra dev alembic downgrade <revision_id>
```

## Data-destructive migrations

Before rolling back any migration that added columns or tables, check:

1. Does the downgrade delete data? Read the `downgrade()` function in the migration file.
2. If yes — restore from backup instead of rolling back:

```bash
# See docs/runbooks/db-restore.md
```

## After rollback

Restart the API so it re-reads the current schema:

```bash
docker compose -f docker-compose.yml --env-file .env.production \
  up -d --no-deps --force-recreate api
```

Check `/healthz` schema revision field:

```bash
curl -sf https://api.revealmarket.xyz/healthz | jq '.schema_revision'
```

## Alembic in Docker context

If running Alembic against the production database from outside Docker, ensure
`RM_DATABASE_URL` points to the correct host (not `postgres` which is the Docker
internal hostname):

```bash
RM_DATABASE_URL="postgresql://market_admin:<REDACTED>@<prod-server-ip>:5432/reveal_market" \
  uv run --project backend/api --extra dev alembic current
```
