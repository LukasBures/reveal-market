#!/usr/bin/env bash
set -euo pipefail

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_info() {
  printf '[%s] %s\n' "$(timestamp)" "$*"
}

log_warn() {
  printf '[%s] WARN: %s\n' "$(timestamp)" "$*" >&2
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
  echo "docker compose or docker-compose is required" >&2
  exit 1
fi

COMPOSE_FILE_ARGS=(-f "${ROOT_DIR}/docker-compose.yml" -f "${ROOT_DIR}/docker-compose.override.yml")
COMPOSE_ENV_ARGS=()
if [[ -f "${ENV_FILE}" && "${SUPPORTS_ENV_FILE}" == true ]]; then
  COMPOSE_ENV_ARGS+=(--env-file "${ENV_FILE}")
fi

MONITOR_ITERATIONS="${MONITOR_ITERATIONS:-10}"
MONITOR_INTERVAL_SECONDS="${MONITOR_INTERVAL_SECONDS:-60}"
LOG_WINDOW_SECONDS="${LOG_WINDOW_SECONDS:-70}"
ERROR_PATTERN="${ERROR_PATTERN:-Traceback|\\| ERROR \\||CRITICAL|unhandled exception}"

cd "${ROOT_DIR}"

if ! docker info >/dev/null 2>&1; then
  echo "docker daemon is not running" >&2
  exit 1
fi

if (( MONITOR_ITERATIONS < 1 )); then
  echo "MONITOR_ITERATIONS must be >= 1" >&2
  exit 1
fi

log_info "monitor.start iterations=${MONITOR_ITERATIONS} interval_seconds=${MONITOR_INTERVAL_SECONDS} log_window_seconds=${LOG_WINDOW_SECONDS}"

for ((iteration = 1; iteration <= MONITOR_ITERATIONS; iteration++)); do
  log_info "monitor.tick ${iteration}/${MONITOR_ITERATIONS}"

  "${COMPOSE_CMD[@]}" "${COMPOSE_FILE_ARGS[@]}" "${COMPOSE_ENV_ARGS[@]}" ps

  while IFS= read -r container_id; do
    [[ -z "${container_id}" ]] && continue
    inspect_line="$(docker inspect --format '{{.Name}}|{{.RestartCount}}' "${container_id}" 2>/dev/null || true)"
    if [[ -z "${inspect_line}" ]]; then
      log_warn "monitor.restart_count.missing container_id=${container_id}"
      continue
    fi
    inspect_line="${inspect_line#/}"
    log_info "monitor.restart_count ${inspect_line}"
  done < <("${COMPOSE_CMD[@]}" "${COMPOSE_FILE_ARGS[@]}" "${COMPOSE_ENV_ARGS[@]}" ps -q)

  log_matches="$("${COMPOSE_CMD[@]}" "${COMPOSE_FILE_ARGS[@]}" "${COMPOSE_ENV_ARGS[@]}" logs --since "${LOG_WINDOW_SECONDS}s" --no-color | rg -n "${ERROR_PATTERN}" || true)"
  if [[ -n "${log_matches}" ]]; then
    log_warn "monitor.errors.detected"
    printf '%s\n' "${log_matches}"
  else
    log_info "monitor.errors.none"
  fi

  if (( iteration < MONITOR_ITERATIONS )); then
    sleep "${MONITOR_INTERVAL_SECONDS}"
  fi
done

log_info "monitor.end"
