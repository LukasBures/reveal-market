#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# run_prod.sh
# -----------------------------------------------------------------------------
# Production-friendly deploy helper.
# - Validates Docker + compose availability and ensures the env/prover artifacts exist.
# - Builds images with cache using BuildKit, always pulling the latest bases (unless --skip-build).
# - Launches docker compose in detached mode (with --wait when supported) and prints service status.
# - Designed for VPS/server usage; run CI-equivalent tests beforehand (make test / contracts/run_local.sh full / npm run build).
#
# Usage: ./run_prod.sh [options] [compose up args...]
# -----------------------------------------------------------------------------

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

log_step() {
  printf '\n[%s] >>> %s\n' "$(timestamp)" "$*"
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ENV_FILE="${ROOT_DIR}/.env.prod"
ENV_FILE="${ENV_FILE:-${DEFAULT_ENV_FILE}}"
SKIP_PROVER_CHECK="${SKIP_PROVER_CHECK:-false}"
PROVER_BUILD_DIR="${ROOT_DIR}/prover/circuits/build"
PROVER_REQUIRED_FILES=(
  "settlement_js/generate_witness.js"
  "settlement_js/settlement.wasm"
  "settlement_final.zkey"
)
DEFAULT_CADDY_FILE="${ROOT_DIR}/docker/caddy/Caddyfile.prod"
TARGET_CADDYFILE="${ROOT_DIR}/docker/caddy/Caddyfile"

prune_docker_artifacts() {
  log_step "Pruning unused Docker images, containers, and build cache"
  docker system prune -af >/dev/null
  docker builder prune -af >/dev/null || true
}

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=("docker" "compose")
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=("docker-compose")
else
  log_warn "docker compose or docker-compose is required"
  exit 1
fi

cd "${ROOT_DIR}"

calc_parallel_builds() {
  local cpus
  if command -v nproc >/dev/null 2>&1; then
    cpus="$(nproc 2>/dev/null || echo 1)"
  elif [[ "$(uname -s)" == "Darwin" ]]; then
    cpus="$(/usr/sbin/sysctl -n hw.ncpu 2>/dev/null || echo 1)"
  else
    cpus=1
  fi
  if [[ -z "${cpus}" || "${cpus}" -lt 2 ]]; then
    echo 1
  else
    echo $((cpus - 1))
  fi
}

supports_wait_flag() {
  if "${COMPOSE_CMD[@]}" up --help 2>&1 | grep -q -- "--wait"; then
    return 0
  fi
  return 1
}

usage() {
  cat <<EOF
Usage: ./run_prod.sh [options] [compose up args...]
  --skip-build           Skip the docker compose build step (useful when pulling pre-built images).
  --env-file <path>      Override the env file check (defaults to ${DEFAULT_ENV_FILE} or \$ENV_FILE).
  --skip-prover-check   Skip Groth16 artifact validation (not recommended).
  --prune                Run 'docker system prune -af' and 'docker builder prune -af' before building.
  -h, --help             Show this help text.
EOF
}

check_env_file() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    cat <<EOF
Missing env file: ${ENV_FILE}
Create one (cp .env.example .env) and update the secrets before running this script.
EOF
    exit 1
  fi
}

check_prover_artifacts() {
  if [[ "${SKIP_PROVER_CHECK}" == "true" ]]; then
    log_warn "Skipping Groth16 prover artifact validation (per flag)."
    return
  fi
  # Prefer the Go-based verifier when available.
  if command -v go >/dev/null 2>&1; then
    if (cd "${ROOT_DIR}/prover" && go run ./cmd/verify-artifacts >/dev/null 2>&1); then
      return
    fi
  fi

  local missing=()
  for rel_path in "${PROVER_REQUIRED_FILES[@]}"; do
    local full_path="${PROVER_BUILD_DIR}/${rel_path}"
    if [[ ! -f "${full_path}" ]]; then
      missing+=("${rel_path}")
    fi
  done

  if (( ${#missing[@]} > 0 )); then
    log_warn "Groth16 artifacts missing; running prover/circuits/generate_keys.sh ..."
    (cd "${ROOT_DIR}/prover/circuits" && bash generate_keys.sh)
  fi
}

check_caddyfile() {
  if [[ ! -f "${DEFAULT_CADDY_FILE}" ]]; then
    log_warn "Missing prod Caddyfile at ${DEFAULT_CADDY_FILE}"
    log_warn "Commit the desired config to docker/caddy/Caddyfile.prod before deploying."
    exit 1
  fi
  if ! cmp -s "${DEFAULT_CADDY_FILE}" "${TARGET_CADDYFILE}" 2>/dev/null; then
    log_step "Preparing prod Caddyfile (${TARGET_CADDYFILE})"
    cp "${DEFAULT_CADDY_FILE}" "${TARGET_CADDYFILE}"
  fi
}

PARALLEL_BUILDS="$(calc_parallel_builds)"
WAIT_FLAG=()
if supports_wait_flag; then
  WAIT_FLAG+=("--wait")
fi
COMPOSE_ENV_ARGS=()

export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
export COMPOSE_PARALLEL_LIMIT="${PARALLEL_BUILDS}"
# Production runs default to real certificates unless explicitly overridden.
export CADDY_TLS_PROFILE="${CADDY_TLS_PROFILE:-tls_prod}"

RUN_BUILD="true"
RUN_PRUNE="false"
UP_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-build)
      RUN_BUILD="false"
      shift
      ;;
    --env-file)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --env-file" >&2
        exit 1
      fi
      ENV_FILE="$2"
      shift 2
      ;;
    --env-file=*)
      ENV_FILE="${1#*=}"
      shift
      ;;
    --skip-prover-check)
      SKIP_PROVER_CHECK="true"
      shift
      ;;
    --prune)
      RUN_PRUNE="true"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      UP_ARGS+=("$@")
      break
      ;;
    *)
      UP_ARGS+=("$1")
      shift
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  log_warn "docker is required to deploy the stack"
  exit 1
fi

check_env_file
check_prover_artifacts
check_caddyfile

if [[ "${RUN_PRUNE}" == "true" ]]; then
  prune_docker_artifacts
fi

SUPPORTS_ENV_FILE=false
if [[ "${COMPOSE_CMD[1]-}" == "compose" ]]; then
  SUPPORTS_ENV_FILE=true
fi

if [[ "${SUPPORTS_ENV_FILE}" == false && "${ENV_FILE}" != "${DEFAULT_ENV_FILE}" ]]; then
  log_warn "compose CLI (${COMPOSE_CMD[*]}) does not support --env-file. Rename env file to .env or use docker compose."
  exit 1
fi

if [[ -n "${ENV_FILE}" && -f "${ENV_FILE}" && "${SUPPORTS_ENV_FILE}" == true ]]; then
  COMPOSE_ENV_ARGS+=(--env-file "${ENV_FILE}")
fi

log_step "Validating docker compose files"
log_info "Running: ${COMPOSE_CMD[*]} ${COMPOSE_ENV_ARGS[*]} config"
"${COMPOSE_CMD[@]}" "${COMPOSE_ENV_ARGS[@]}" config >/dev/null

if [[ "${RUN_BUILD}" == "true" ]]; then
  log_step "Building Docker images (cached layers, pulling latest bases, parallel=${COMPOSE_PARALLEL_LIMIT})"
  log_info "Running: ${COMPOSE_CMD[*]} ${COMPOSE_ENV_ARGS[*]} build --parallel --pull"
  "${COMPOSE_CMD[@]}" "${COMPOSE_ENV_ARGS[@]}" build --parallel --pull
else
  log_warn "Skipping docker compose build step (per --skip-build)."
fi

log_step "Starting services in detached mode"
UP_CMD=("${COMPOSE_CMD[@]}" "${COMPOSE_ENV_ARGS[@]}" up "-d" "--remove-orphans" "${WAIT_FLAG[@]}")
if [[ ${#UP_ARGS[@]} -gt 0 ]]; then
  UP_CMD+=("${UP_ARGS[@]}")
fi
log_info "Running: ${UP_CMD[*]}"
"${UP_CMD[@]}"

log_step "Service status"
log_info "Running: ${COMPOSE_CMD[*]} ${COMPOSE_ENV_ARGS[*]} ps"
"${COMPOSE_CMD[@]}" "${COMPOSE_ENV_ARGS[@]}" ps

# Emit a concise health summary when supported (Docker Compose v2+).
if "${COMPOSE_CMD[@]}" ps --help 2>/dev/null | grep -q -- "--format"; then
  log_step "Health summary"
  HEALTH_SUMMARY_SCRIPT="$(cat <<'PY'
import json
import sys

data = json.load(sys.stdin)
for svc in data:
    name = svc.get("Name")
    state = svc.get("State")
    health = svc.get("Health")
    print(f"{name:30s} state={state} health={health}")
PY
)"
  "${COMPOSE_CMD[@]}" "${COMPOSE_ENV_ARGS[@]}" ps --format json | python -c "${HEALTH_SUMMARY_SCRIPT}"
fi

log_step "Deployment complete"
