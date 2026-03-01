#!/usr/bin/env bash
set -euo pipefail

timestamp() {
  date +"%Y-%m-%d %H:%M:%S"
}

log_info() {
  printf '[%s] %s\n' "$(timestamp)" "$*"
}

log_warn() {
  printf '[%s] WARN: %s\n' "$(timestamp)" "$*" >&2
}

log_error() {
  printf '[%s] ERROR: %s\n' "$(timestamp)" "$*" >&2
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_ENV_FILE="${ROOT_DIR}/.env.local"
FALLBACK_ENV_FILE="${ROOT_DIR}/.env"

if [[ -z "${ENV_FILE:-}" ]]; then
  if [[ -f "${DEFAULT_ENV_FILE}" ]]; then
    ENV_FILE="${DEFAULT_ENV_FILE}"
  elif [[ -f "${FALLBACK_ENV_FILE}" ]]; then
    ENV_FILE="${FALLBACK_ENV_FILE}"
  else
    ENV_FILE="${DEFAULT_ENV_FILE}"
  fi
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=("docker" "compose")
  SUPPORTS_ENV_FILE=true
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=("docker-compose")
  SUPPORTS_ENV_FILE=false
else
  log_error "docker compose or docker-compose is required"
  exit 1
fi

COMPOSE_FILE_ARGS=(-f "${ROOT_DIR}/docker-compose.yml" -f "${ROOT_DIR}/docker-compose.override.yml")
COMPOSE_ENV_ARGS=()
if [[ -f "${ENV_FILE}" && "${SUPPORTS_ENV_FILE}" == true ]]; then
  COMPOSE_ENV_ARGS+=(--env-file "${ENV_FILE}")
fi

WAIT_RETRIES="${SMOKE_WAIT_RETRIES:-36}"
WAIT_INTERVAL_SECONDS="${SMOKE_WAIT_INTERVAL_SECONDS:-5}"
HTTP_RETRIES="${SMOKE_HTTP_RETRIES:-24}"
HTTP_INTERVAL_SECONDS="${SMOKE_HTTP_INTERVAL_SECONDS:-5}"
HTTP_TIMEOUT_SECONDS="${SMOKE_HTTP_TIMEOUT_SECONDS:-5}"
MAX_RESTARTS="${SMOKE_MAX_RESTARTS:-0}"
SMOKE_HEARTBEATS_SECRET_FROM_ENV=<REDACTED>
SMOKE_HEARTBEATS_URL="${SMOKE_HEARTBEATS_URL:-http://127.0.0.1:8000/healthz/heartbeats}"
SMOKE_HEARTBEAT_SUMMARY_URL="${SMOKE_HEARTBEAT_SUMMARY_URL:-http://127.0.0.1:8000/healthz/heartbeats/summary}"

EXPECTED_SERVICES_CSV="${SMOKE_EXPECTED_SERVICES:-postgres,redis,api,worker,hedger,relayer,frontend,prover,streamer}"
IFS=',' read -r -a EXPECTED_SERVICES <<<"${EXPECTED_SERVICES_CSV}"

ENDPOINTS_CSV="${SMOKE_ENDPOINTS:-http://127.0.0.1:8000/healthz,http://127.0.0.1:8100/healthz,http://127.0.0.1:8090/healthz,http://127.0.0.1:8088/healthz,http://127.0.0.1:8085/healthz,http://127.0.0.1:3000/healthz,http://127.0.0.1:3000/,${SMOKE_HEARTBEAT_SUMMARY_URL}}"
IFS=',' read -r -a ENDPOINTS <<<"${ENDPOINTS_CSV}"

cd "${ROOT_DIR}"

if ! docker info >/dev/null 2>&1; then
  log_error "docker daemon is not running"
  exit 1
fi

load_secret_from_env_file() {
  local key="$1"
  python3 - "${ENV_FILE}" "${key}" <<'PY'
import pathlib
import sys

env_path = pathlib.Path(sys.argv[1])
lookup_key = sys.argv[2]
if not env_path.exists():
    raise SystemExit(0)

for raw_line in env_path.read_text().splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[len("export ") :].strip()
    if "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key.strip() != lookup_key:
        continue
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'":
        cleaned = cleaned[1:-1]
    print(cleaned)
    break
PY
}

check_services_ready() {
  local services_csv="$1"
  local ps_output
  ps_output="$("${COMPOSE_CMD[@]}" "${COMPOSE_FILE_ARGS[@]}" "${COMPOSE_ENV_ARGS[@]}" ps --format json)"
  python3 - "${services_csv}" <<'PY' <<<"${ps_output}"
import json
import sys

expected = [part.strip() for part in sys.argv[1].split(",") if part.strip()]
raw = sys.stdin.read().strip()
entries = []

if raw:
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            entries = [item for item in parsed if isinstance(item, dict)]
        elif isinstance(parsed, dict):
            entries = [parsed]
    except Exception:
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                entries.append(item)

def normalize_service(entry: dict) -> str:
    service = entry.get("Service")
    if isinstance(service, str) and service:
        return service
    name = entry.get("Name")
    if isinstance(name, str) and name:
        if name.startswith("reveal-market-"):
            return name.removeprefix("reveal-market-")
        if "-" in name:
            return name.split("-")[-1]
        return name
    return ""

services: dict[str, dict] = {}
for entry in entries:
    service = normalize_service(entry)
    if service:
        services[service] = entry

missing: list[str] = []
invalid: list[str] = []

for service in expected:
    entry = services.get(service)
    if not entry:
        missing.append(service)
        continue

    state = str(entry.get("State", "")).lower()
    health = str(entry.get("Health", "")).lower()
    if state != "running":
        invalid.append(f"{service}:state={state or 'unknown'}")
        continue
    if health and health not in {"healthy"}:
        invalid.append(f"{service}:health={health}")
        continue
    print(f"{service}: state={state} health={health or 'n/a'}")

if missing:
    print("missing services: " + ", ".join(sorted(missing)))
if invalid:
    print("not ready: " + ", ".join(sorted(invalid)))

if missing or invalid:
    sys.exit(1)
PY
}

wait_for_services() {
  local services_csv="$1"
  local attempt
  for ((attempt = 1; attempt <= WAIT_RETRIES; attempt++)); do
    if check_services_ready "${services_csv}"; then
      log_info "All expected containers are running and healthy."
      return 0
    fi
    log_warn "Container health check attempt ${attempt}/${WAIT_RETRIES} failed; retrying in ${WAIT_INTERVAL_SECONDS}s."
    sleep "${WAIT_INTERVAL_SECONDS}"
  done
  log_error "Timed out waiting for containers to become healthy."
  return 1
}

wait_for_endpoint() {
  local endpoint="$1"
  local attempt
  for ((attempt = 1; attempt <= HTTP_RETRIES; attempt++)); do
    if curl -fsS --max-time "${HTTP_TIMEOUT_SECONDS}" -o /dev/null "${endpoint}"; then
      log_info "HTTP OK: ${endpoint}"
      return 0
    fi
    sleep "${HTTP_INTERVAL_SECONDS}"
  done
  log_error "HTTP check failed after ${HTTP_RETRIES} attempts: ${endpoint}"
  return 1
}

check_restart_counts() {
  local max_restarts="$1"
  local container_ids
  container_ids="$("${COMPOSE_CMD[@]}" "${COMPOSE_FILE_ARGS[@]}" "${COMPOSE_ENV_ARGS[@]}" ps -q)"
  if [[ -z "${container_ids}" ]]; then
    log_error "No containers found for compose project."
    return 1
  fi

  while IFS='|' read -r name restart_count; do
    [[ -z "${name}" ]] && continue
    restart_count="${restart_count:-0}"
    log_info "restart_count ${name}=${restart_count}"
    if (( restart_count > max_restarts )); then
      log_error "Restart threshold exceeded for ${name}: ${restart_count} > ${max_restarts}"
      return 1
    fi
  done < <(docker inspect --format '{{.Name}}|{{.RestartCount}}' ${container_ids} | sed 's#^/##')
}

wait_for_secret_endpoint() {
  local endpoint="$1"
  local secret="$2"
  local attempt
  for ((attempt = 1; attempt <= HTTP_RETRIES; attempt++)); do
    if curl -fsS --max-time "${HTTP_TIMEOUT_SECONDS}" -H "X-Internal-Secret: ${secret}" -o /dev/null "${endpoint}"; then
      log_info "HTTP OK (secret): ${endpoint}"
      return 0
    fi
    sleep "${HTTP_INTERVAL_SECONDS}"
  done
  log_error "Secret endpoint check failed after ${HTTP_RETRIES} attempts: ${endpoint}"
  return 1
}

log_info "Running local smoke checks..."
wait_for_services "${EXPECTED_SERVICES_CSV}"

for endpoint in "${ENDPOINTS[@]}"; do
  wait_for_endpoint "${endpoint}"
done

if [[ -z "${SMOKE_HEARTBEATS_SECRET:-}" && "${SMOKE_HEARTBEATS_SECRET_FROM_ENV}" == "true" ]]; then
  SMOKE_HEARTBEATS_SECRET=<REDACTED>
fi
if [[ -n "${SMOKE_HEARTBEATS_SECRET:-}" ]]; then
  wait_for_secret_endpoint "${SMOKE_HEARTBEATS_URL}" "${SMOKE_HEARTBEATS_SECRET}"
else
  log_warn "Skipping secret heartbeat dashboard check; set SMOKE_HEARTBEATS_SECRET to enable."
fi

check_restart_counts "${MAX_RESTARTS}"
log_info "Smoke checks passed."
