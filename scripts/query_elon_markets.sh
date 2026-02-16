#!/usr/bin/env bash
set -euo pipefail

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -f .env.local ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env.local
  set +a
fi

compose=(docker compose)
if [[ -f docker-compose.override.yml ]]; then
  compose+=( -f docker-compose.yml -f docker-compose.override.yml )
fi

if [[ -z "${REDIS_PASSWORD:-}" ]]; then
  if [[ -f docker/redis/redis.conf ]]; then
    REDIS_PASSWORD=$(rg -n "requirepass" docker/redis/redis.conf | awk '{print $2}' | head -n1 || true)
    export REDIS_PASSWORD
  fi
fi

if ! ${compose[@]} ps postgres >/dev/null 2>&1; then
  echo "Postgres container not running in compose." >&2
  exit 1
fi

${compose[@]} exec -T postgres psql -U market_admin -d reveal_market \
  -c "select event_id, title, group_slug, event_key from markets where lower(title) like '%elon musk post%' order by event_id limit 40;"
