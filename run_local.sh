#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# run_local.sh
# -----------------------------------------------------------------------------
# Full rebuild + launch script for developers.
# - Enables BuildKit + parallel builds (leaving one CPU free).
# - Defaults to a --no-cache + --pull compose build so every layer is fresh (use --cache to reuse layers).
# - Optional --skip-build for faster iterations when only restarting containers.
# - Starts docker compose (with --remove-orphans) in the foreground so logs stream to the terminal (use --detach to background).
# - Tip: run `make test` (backend) / `npm run test` (frontend) before calling this to catch errors earlier.
#
# Usage: ./run_local.sh [options] [extra docker-compose args]
#
# Examples:
#   ./run_local.sh
#   ./run_local.sh api worker   # Bring up subset of services after rebuild
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
DEFAULT_ENV_FILE="${ROOT_DIR}/.env.local"
ENV_FILE="${ENV_FILE:-${DEFAULT_ENV_FILE}}"
PROVER_BUILD_DIR="${ROOT_DIR}/prover/circuits/build"
PROVER_REQUIRED_FILES=(
  "settlement_js/generate_witness.js"
  "settlement_js/settlement.wasm"
  "settlement_final.zkey"
)
SKIP_PROVER_CHECK="${SKIP_PROVER_CHECK:-false}"

prune_docker_artifacts() {
  log_step "Pruning unused Docker data"
  docker system prune -af >/dev/null
}

detect_cpu_count() {
  local cpus
  if command -v nproc >/dev/null 2>&1; then
    cpus="$(nproc 2>/dev/null || echo 1)"
  elif [[ "$(uname -s)" == "Darwin" ]]; then
    cpus="$(/usr/sbin/sysctl -n hw.ncpu 2>/dev/null || echo 1)"
  else
    cpus=1
  fi
  if [[ -z "${cpus}" || "${cpus}" -lt 1 ]]; then
    echo 1
  else
    echo "${cpus}"
  fi
}

# Compose v2 (docker compose) is preferred; fall back to classic docker-compose.
if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=("docker" "compose")
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=("docker-compose")
else
  echo "docker compose or docker-compose is required" >&2
  exit 1
fi

calc_parallel_builds() {
  # Compose refuses to parallelise more builds than CPUs, so detect the host
  # count once and leave one core idle to keep laptops responsive.
  local cpus="${1:-}"
  if [[ -z "${cpus}" ]]; then
    cpus="$(detect_cpu_count)"
  fi
  if [[ -z "${cpus}" || "${cpus}" -lt 2 ]]; then
    echo 1
  else
    echo $((cpus - 1))
  fi
}

CPU_COUNT="$(detect_cpu_count)"
PARALLEL_BUILDS="$(calc_parallel_builds "${CPU_COUNT}")"
NEXT_BUILD_WORKERS="${NEXT_BUILD_WORKERS:-${CPU_COUNT}}"
export NEXT_BUILD_WORKERS
COMPOSE_ENV_ARGS=()

ensure_prover_artifacts() {
  if [[ "${SKIP_PROVER_CHECK}" == "true" ]]; then
    log_warn "Skipping Groth16 artifact validation (SKIP_PROVER_CHECK=true)."
    return
  fi
  local missing=()
  for rel_path in "${PROVER_REQUIRED_FILES[@]}"; do
    if [[ ! -f "${PROVER_BUILD_DIR}/${rel_path}" ]]; then
      missing+=("${rel_path}")
    fi
  done
  if (( ${#missing[@]} > 0 )); then
    cat <<EOF
Missing Groth16 artifacts under ${PROVER_BUILD_DIR}.
Run 'bash prover/circuits/generate_keys.sh' to produce the proving/witness assets before starting Docker.
Missing files:
$(printf '  - %s\n' "${missing[@]}")
Set SKIP_PROVER_CHECK=true to bypass this check (not recommended).
EOF
    exit 1
  fi
}

# Enable BuildKit + Compose's CLI mode so builds are faster and parallelizable.
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
export COMPOSE_PARALLEL_LIMIT="${PARALLEL_BUILDS}"

BUILD_FLAG="--no-cache"
RUN_BUILD="true"
RUN_PRUNE="${RUN_PRUNE:-false}"
DETACH_MODE="false"
UP_ARGS=()
BUILD_SERVICES=()

usage() {
  cat <<EOF
Usage: ./run_local.sh [--cache|--no-cache] [--skip-build] [compose up args...]
  --cache          Reuse existing build layers.
  --no-cache       Force a clean rebuild (default).
  --skip-build     Skip the docker compose build step entirely.
  --build-services Comma-separated list of services to rebuild (e.g., api,worker,frontend).
  --env-file PATH  Use a specific env file (defaults to ${DEFAULT_ENV_FILE} or \$ENV_FILE).
  --prune          Run 'docker system prune -af' before building (disabled by default).
  --detach         Start docker compose in the background (default streams logs in foreground).
  -h, --help       Show this help text.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cache)
      BUILD_FLAG=""
      shift
      ;;
    --no-cache)
      BUILD_FLAG="--no-cache"
      shift
      ;;
    --build-services)
      if [[ $# -lt 2 ]]; then
        log_warn "Missing value for --build-services (expected comma-separated list)"
        exit 1
      fi
      IFS="," read -r -a BUILD_SERVICES <<<"$2"
      shift 2
      ;;
    --build-services=*)
      IFS="," read -r -a BUILD_SERVICES <<<"${1#*=}"
      shift
      ;;
    --skip-build)
      RUN_BUILD="false"
      shift
      ;;
    --env-file)
      if [[ $# -lt 2 ]]; then
        log_warn "Missing value for --env-file"
        exit 1
      fi
      ENV_FILE="$2"
      shift 2
      ;;
    --env-file=*)
      ENV_FILE="${1#*=}"
      shift
      ;;
    --prune)
      RUN_PRUNE="true"
      shift
      ;;
    --detach)
      DETACH_MODE="true"
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

# Sanity-check that Docker is installed.
if ! command -v docker >/dev/null 2>&1; then
    log_warn "docker is required to run the local stack"
    exit 1
fi

cd "${ROOT_DIR}"

if [[ "${RUN_PRUNE}" == "true" ]]; then
  prune_docker_artifacts
fi

ensure_prover_artifacts

# Configure env file usage
if docker compose version >/dev/null 2>&1; then
  SUPPORTS_ENV_FILE=true
else
  SUPPORTS_ENV_FILE=false
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  log_warn "Env file ${ENV_FILE} not found; docker compose will fall back to defaults."
else
  if [[ "${SUPPORTS_ENV_FILE}" == true ]]; then
    COMPOSE_ENV_ARGS+=(--env-file "${ENV_FILE}")
  elif [[ "${ENV_FILE}" != "${DEFAULT_ENV_FILE}" ]]; then
    log_warn "compose CLI (${COMPOSE_CMD[*]}) does not support --env-file; rename env file to .env or switch to docker compose."
  fi
fi

log_step "Validating docker compose files"
log_info "Running: ${COMPOSE_CMD[*]} ${COMPOSE_ENV_ARGS[*]} config"
"${COMPOSE_CMD[@]}" "${COMPOSE_ENV_ARGS[@]}" config >/dev/null
if [[ "${RUN_BUILD}" == "true" ]]; then
  BUILD_DESC="${BUILD_FLAG:-cached layers}"
  log_step "Building images (${BUILD_DESC}, pull latest bases, parallel=${COMPOSE_PARALLEL_LIMIT})"
  BUILD_OPTS=(--parallel --pull)
  if [[ -n "${BUILD_FLAG}" ]]; then
    BUILD_OPTS+=("${BUILD_FLAG}")
  fi
  BUILD_CMD=("${COMPOSE_CMD[@]}" "${COMPOSE_ENV_ARGS[@]}" build "${BUILD_OPTS[@]}")
  if [[ ${#BUILD_SERVICES[@]} -gt 0 ]]; then
    BUILD_CMD+=("${BUILD_SERVICES[@]}")
  fi
  log_info "Running: ${BUILD_CMD[*]}"
  "${BUILD_CMD[@]}"
else
  log_warn "Skipping docker compose build step (per --skip-build)."
fi

log_step "Starting services"
UP_CMD=("${COMPOSE_CMD[@]}" "${COMPOSE_ENV_ARGS[@]}" up "--remove-orphans")
if [[ "${DETACH_MODE}" == "true" ]]; then
  UP_CMD+=("--detach")
fi
if [[ ${#UP_ARGS[@]} -gt 0 ]]; then
  UP_CMD+=("${UP_ARGS[@]}")
fi
log_info "Running: ${UP_CMD[*]}"
"${UP_CMD[@]}"

API_PORT="${API_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
POSTGRES_URI="${POSTGRES_URI:-postgres://market_admin:<REDACTED>@localhost:5432/reveal_market}"
REDIS_CMD="${REDIS_CMD:-redis-cli -h localhost -p 6379}"

cat <<EOF
------------------------------------------------------------
Stack ready. Useful URLs while running locally:
  • API docs / health:      http://localhost:${API_PORT}/docs  | http://localhost:${API_PORT}/health
  • Hedger admin / metrics: http://localhost:8090/admin/exposures | http://localhost:8090/metrics
  • Perf / SLA metrics:     http://localhost:${API_PORT}/health/heartbeats
  • Frontend / marketing:   http://localhost:${FRONTEND_PORT}/
  • Postgres (psql):        ${POSTGRES_URI}
  • Redis (CLI):            ${REDIS_CMD}
------------------------------------------------------------
EOF

if [[ "${DETACH_MODE}" == "false" ]]; then
  cat <<'EOF'
📜 Streaming logs (Ctrl+C to stop):
------------------------------------------------------------
EOF
  log_info "Running: ${COMPOSE_CMD[*]} ${COMPOSE_ENV_ARGS[*]} logs -f"
  "${COMPOSE_CMD[@]}" "${COMPOSE_ENV_ARGS[@]}" logs -f
else
  cat <<EOF
📜 Services are running in the background (started with --detach).
    View logs with: ${COMPOSE_CMD[*]} logs -f ${UP_ARGS[*]}
EOF
fi
