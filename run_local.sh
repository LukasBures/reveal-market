#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# run_local.sh
# -----------------------------------------------------------------------------
# Full rebuild + launch script for developers.
# - Enables BuildKit + parallel builds (leaving one CPU free).
# - Defaults to cached compose builds so rebuilds are fast (pass --no-cache to force a clean build).
# - Optional --skip-build for faster iterations when only restarting containers; service arguments limit rebuild scope.
# - Starts docker compose (with --remove-orphans) in the foreground so logs stream to the terminal (use --detach to background).
# - Tip: run `make test` (backend) / `npm run test` (frontend) before calling this to catch errors earlier.
# - Python services use uv; for local API/worker tooling run `uv sync --extra dev` inside backend/api and backend/worker.
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
FALLBACK_ENV_FILE="${ROOT_DIR}/.env"
# Resolve env file to seed (ENV_FILE override > .env.local > .env)
if [[ -z "${ENV_FILE:-}" ]]; then
  if [[ -f "${DEFAULT_ENV_FILE}" ]]; then
    ENV_FILE="${DEFAULT_ENV_FILE}"
  elif [[ -f "${FALLBACK_ENV_FILE}" ]]; then
    ENV_FILE="${FALLBACK_ENV_FILE}"
  else
    ENV_FILE="${DEFAULT_ENV_FILE}"
  fi
fi
FRONTEND_ENV_FILE="${ROOT_DIR}/frontend/.env.local"
if [[ -f "${ENV_FILE}" ]]; then
  log_info "Seeding frontend env from ${ENV_FILE} -> ${FRONTEND_ENV_FILE}"
  cp -f "${ENV_FILE}" "${FRONTEND_ENV_FILE}"
else
  log_warn "No env file found at ${ENV_FILE}; frontend/.env.local will not be seeded"
fi
export ENV_FILE
export FRONTEND_ENV_FILE
PROVER_BUILD_DIR="${ROOT_DIR}/prover/circuits/build"
PROVER_ARTIFACTS_DIR="${ROOT_DIR}/prover/artifacts"
PROVER_ARTIFACTS_BUILD_DIR="${PROVER_ARTIFACTS_DIR}/prover/circuits/build"
PROVER_ARTIFACTS_URL="${PROVER_ARTIFACTS_URL:-}"
PROVER_ARTIFACTS_SHA256="${PROVER_ARTIFACTS_SHA256:-}"
PROVER_REQUIRED_FILES=(
  "settlement_js/generate_witness.js"
  "settlement_js/settlement.wasm"
  "settlement_final.zkey"
)
SKIP_PROVER_CHECK="${SKIP_PROVER_CHECK:-false}"
APK_REPO_URL="${APK_REPO_URL:-https://dl-cdn.alpinelinux.org/alpine}"
APK_FALLBACK_URL="${APK_FALLBACK_URL:-https://mirror.leaseweb.net/alpine}"
ALPINE_BASE_IMAGES=("node:20-alpine" "python:3.12-alpine")

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

detect_alpine_version() {
  local image="$1"
  local release
  if ! release="$(docker run --rm --entrypoint=cat "${image}" /etc/alpine-release 2>/dev/null || true)"; then
    release=""
  fi
  if [[ -z "${release}" ]]; then
    echo ""
    return 0
  fi
  echo "${release}" | cut -d. -f1,2
}

ensure_docker_running() {
  if ! docker info >/dev/null 2>&1; then
    log_warn "Docker daemon is not running. Start Docker and try again."
    exit 1
  fi
}

check_apk_mirror() {
  if ! command -v curl >/dev/null 2>&1; then
    log_warn "curl not found; skipping APK mirror preflight (APK_REPO_URL=${APK_REPO_URL})."
    return
  fi
  local failures=0
  for image in "${ALPINE_BASE_IMAGES[@]}"; do
    local version
    version="$(detect_alpine_version "${image}")"
    if [[ -z "${version}" ]]; then
      log_warn "Could not detect Alpine version for ${image}; skipping mirror check for this image."
      continue
    fi
    local index_url="${APK_REPO_URL}/v${version}/main/x86_64/APKINDEX.tar.gz"
    if ! curl -fsI --max-time 8 "${index_url}" >/dev/null 2>&1; then
      log_warn "APK mirror check failed for ${image} (version ${version}) at ${index_url}; DNS/mirror may be flaky."
      failures=1
    fi
  done
  if [[ "${failures}" -eq 0 ]]; then
    log_info "APK mirror reachable at ${APK_REPO_URL} for tested Alpine bases."
  else
    log_warn "APK mirror preflight encountered errors. Consider overriding APK_REPO_URL to a known-good mirror (e.g., https://dl-cdn.alpinelinux.org/alpine)."
    if [[ -n "${APK_FALLBACK_URL}" ]]; then
      log_info "Fallback mirror configured: ${APK_FALLBACK_URL}"
    fi
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
# Always load base + local override.
COMPOSE_FILE_ARGS=(-f "${ROOT_DIR}/docker-compose.yml" -f "${ROOT_DIR}/docker-compose.override.yml")

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
PARALLEL_BUILDS_DEFAULT="$(calc_parallel_builds "${CPU_COUNT}")"
PARALLEL_BUILDS="${PARALLEL_BUILDS:-${PARALLEL_BUILDS_DEFAULT}}"
NEXT_BUILD_WORKERS="${NEXT_BUILD_WORKERS:-${CPU_COUNT}}"
export NEXT_BUILD_WORKERS
# Default Caddy TLS profile to internal for local runs (overridable).
export CADDY_TLS_PROFILE="${CADDY_TLS_PROFILE:-tls_local}"
COMPOSE_ENV_ARGS=()
WAIT_FLAG=()

list_missing_prover_files() {
  for rel_path in "${PROVER_REQUIRED_FILES[@]}"; do
    if [[ ! -s "${PROVER_BUILD_DIR}/${rel_path}" ]]; then
      echo "${rel_path}"
    fi
  done
}

seed_prover_artifacts_from_submodule() {
  if [[ ! -d "${PROVER_ARTIFACTS_DIR}" ]]; then
    return 1
  fi
  if command -v git >/dev/null 2>&1; then
    if ! git -C "${ROOT_DIR}" submodule update --init --recursive prover/artifacts >/dev/null 2>&1; then
      log_warn "Failed to update prover/artifacts submodule; proceeding without seeding."
    fi
  else
    log_warn "git not found; cannot refresh prover/artifacts submodule."
    return 1
  fi
  if [[ ! -d "${PROVER_ARTIFACTS_BUILD_DIR}" ]]; then
    return 1
  fi
  log_step "Seeding prover artifacts from prover/artifacts"
  rm -rf "${PROVER_BUILD_DIR}"
  mkdir -p "${PROVER_BUILD_DIR}"
  cp -a "${PROVER_ARTIFACTS_BUILD_DIR}/." "${PROVER_BUILD_DIR}/"
  return 0
}

sync_prover_from_artifacts_source() {
  if [[ ! -d "${PROVER_ARTIFACTS_BUILD_DIR}" ]]; then
    return 1
  fi
  log_step "Syncing Groth16 artifacts from prover/artifacts (source of truth)"
  rm -rf "${PROVER_BUILD_DIR}"
  mkdir -p "${PROVER_BUILD_DIR}"
  cp -a "${PROVER_ARTIFACTS_BUILD_DIR}/." "${PROVER_BUILD_DIR}/"
  sync_prover_caches
  return 0
}

download_prover_artifacts() {
  if [[ -z "${PROVER_ARTIFACTS_URL}" ]]; then
    return 1
  fi
  if [[ ! -x "${ROOT_DIR}/prover/scripts/download_artifacts.sh" ]]; then
    log_warn "prover/scripts/download_artifacts.sh is missing or not executable; cannot download artifacts."
    return 1
  fi
  log_step "Downloading prover artifacts from ${PROVER_ARTIFACTS_URL}"
  if (cd "${ROOT_DIR}/prover" && PROVER_ARTIFACTS_URL="${PROVER_ARTIFACTS_URL}" PROVER_ARTIFACTS_SHA256="${PROVER_ARTIFACTS_SHA256}" ./scripts/download_artifacts.sh); then
    return 0
  fi
  log_warn "Failed to download prover artifacts from ${PROVER_ARTIFACTS_URL}"
  return 1
}

sync_prover_caches() {
  local vk_src="${PROVER_BUILD_DIR}/settlement_deploy.json"
  if [[ ! -s "${vk_src}" ]]; then
    vk_src="${PROVER_BUILD_DIR}/settlement_vk.json"
  fi
  if [[ ! -s "${vk_src}" ]]; then
    return
  fi
  local cache_targets=(
    "${ROOT_DIR}/contracts/cache/settlement-vk.json"
    "${ROOT_DIR}/contracts/zen/cache/settlement-vk.json"
  )
  for dest in "${cache_targets[@]}"; do
    mkdir -p "$(dirname "${dest}")"
    cp "${vk_src}" "${dest}"
  done
}

ensure_prover_artifacts() {
  if [[ "${SKIP_PROVER_CHECK}" == "true" ]]; then
    log_warn "Skipping Groth16 artifact validation (SKIP_PROVER_CHECK=true)."
    return
  fi
  local missing=()
  log_step "Validating prover artifacts"
  mapfile -t missing < <(list_missing_prover_files)
  if (( ${#missing[@]} > 0 )); then
    log_warn "Groth16 artifacts missing; attempting to seed from prover/artifacts or download."
    seed_prover_artifacts_from_submodule || true
    mapfile -t missing < <(list_missing_prover_files)
  fi
  if (( ${#missing[@]} > 0 )); then
    download_prover_artifacts || true
    mapfile -t missing < <(list_missing_prover_files)
  fi
  if (( ${#missing[@]} > 0 )); then
    cat <<EOF
Missing Groth16 artifacts under ${PROVER_BUILD_DIR}.
Run 'bash prover/circuits/generate_keys.sh' or set PROVER_ARTIFACTS_URL/PROVER_ARTIFACTS_SHA256 to fetch a packaged build before starting Docker.
Missing files:
$(printf '  - %s\n' "${missing[@]}")
Set SKIP_PROVER_CHECK=true to bypass this check (not recommended).
EOF
    exit 1
  fi
  sync_prover_caches
}

disable_next_telemetry() {
  if [[ ! -d "${ROOT_DIR}/frontend" ]]; then
    return
  fi
  if ! command -v npx >/dev/null 2>&1; then
    log_warn "Skipping Next.js telemetry disable (npx not found)."
    return
  fi
  log_step "Disabling Next.js telemetry"
  if ! (cd "${ROOT_DIR}/frontend" && npx next telemetry disable >/dev/null 2>&1); then
    log_warn "Failed to disable Next.js telemetry; continuing."
  fi
}

# Enable BuildKit + Compose's CLI mode so builds are faster and parallelizable.
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
export COMPOSE_PARALLEL_LIMIT="${PARALLEL_BUILDS}"
export APK_REPO_URL
export APK_FALLBACK_URL

BUILD_FLAG=""
RUN_BUILD="true"
USE_BAKE="true"
RUN_PRUNE="${RUN_PRUNE:-false}"
DETACH_MODE="false"
UP_ARGS=()
BUILD_SERVICES=()

usage() {
  cat <<EOF
Usage: ./run_local.sh [--cache|--no-cache] [--skip-build] [compose up args...]
  --cache          Reuse existing build layers (default).
  --no-cache       Force a clean rebuild.
  --skip-build     Skip the docker compose build step entirely.
  --bake           Use 'docker buildx bake' for parallel builds with shared base layers (default).
  --no-bake        Fall back to 'docker compose build' instead of bake.
  --build-services Comma-separated list of services to rebuild (e.g., api,worker,frontend).
  --env-file PATH  Use a specific env file (defaults to ${DEFAULT_ENV_FILE} or \$ENV_FILE).
  --prune          Run 'docker system prune -af' before building (disabled by default; clears caches).
  --detach         Start docker compose in the background (default streams logs in foreground).
  -h, --help       Show this help text.

Passing service names (e.g., frontend,api) limits both the build and up steps to those services.
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
    --bake)
      USE_BAKE="true"
      shift
      ;;
    --no-bake)
      USE_BAKE="false"
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
      # Treat bare arguments as service names or compose flags.
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
ensure_docker_running

cd "${ROOT_DIR}"

if [[ "${RUN_PRUNE}" == "true" ]]; then
  prune_docker_artifacts
fi

sync_prover_from_artifacts_source || true
ensure_prover_artifacts
check_apk_mirror
disable_next_telemetry

# Configure env file usage
SUPPORTS_ENV_FILE=false
if docker compose version >/dev/null 2>&1; then
  SUPPORTS_ENV_FILE=true
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

supports_wait_flag() {
  if "${COMPOSE_CMD[@]}" up --help 2>&1 | grep -q -- "--wait"; then
    return 0
  fi
  return 1
}

if supports_wait_flag; then
  WAIT_FLAG+=("--wait")
fi

log_step "Validating docker compose files"
log_info "Running: ${COMPOSE_CMD[*]} ${COMPOSE_FILE_ARGS[*]} ${COMPOSE_ENV_ARGS[*]} config"
"${COMPOSE_CMD[@]}" "${COMPOSE_FILE_ARGS[@]}" "${COMPOSE_ENV_ARGS[@]}" config >/dev/null
if [[ "${RUN_BUILD}" == "true" ]]; then
  # If the user requested specific services to run and did not pass --build-services,
  # limit the build to those services to avoid rebuilding the entire stack.
  if [[ ${#BUILD_SERVICES[@]} -eq 0 && ${#UP_ARGS[@]} -gt 0 ]]; then
  BUILD_SERVICES=("${UP_ARGS[@]}")
fi

if [[ "${USE_BAKE}" == "true" ]]; then
  # Run bake in a subshell so the env exports don't leak into docker compose up
  # (compose does its own env-file interpolation and raw ${VAR} literals would
  # override the expanded values).
  (
    # docker buildx bake has no --env-file flag; export env vars into the shell
    # so bake can interpolate ${VAR} references in docker-compose.yml.
    if [[ -f "${ENV_FILE}" ]]; then
      while IFS= read -r _line || [[ -n "${_line}" ]]; do
        [[ "${_line}" =~ ^[[:space:]]*# ]] && continue
        [[ "${_line}" =~ ^[[:space:]]*$ ]] && continue
        [[ "${_line}" == *=* ]] || continue
        _key="${_line%%=*}"
        _val="${_line#*=}"
        # Strip surrounding quotes (Docker env-file compat).
        if [[ "${_val}" =~ ^\"(.*)\"$ ]]; then
          _val="${BASH_REMATCH[1]}"
        elif [[ "${_val}" =~ ^\'(.*)\'$ ]]; then
          _val="${BASH_REMATCH[1]}"
        fi
        export "${_key}=${_val}"
      done < "${ENV_FILE}"
    fi
    log_step "Building images with docker buildx bake (parallel, shared bases)"
    BAKE_CMD=("docker" "buildx" "bake")
    if [[ -n "${BUILD_FLAG}" ]]; then
      BAKE_CMD+=("${BUILD_FLAG}")
    fi
    if [[ ${#BUILD_SERVICES[@]} -gt 0 ]]; then
      BAKE_CMD+=("${BUILD_SERVICES[@]}")
    fi
    log_info "Running: ${BAKE_CMD[*]}"
    if ! "${BAKE_CMD[@]}"; then
      log_warn "docker buildx bake failed."
      exit 1
    fi
  )
else
BUILD_DESC="${BUILD_FLAG:-cached layers}"
log_step "Building images (${BUILD_DESC}, parallel=${COMPOSE_PARALLEL_LIMIT})"
run_compose_build() {
  local parallel_flag="${1:-true}"
  local parallel_limit="${2:-${COMPOSE_PARALLEL_LIMIT}}"
  local opts=(--build-arg "APK_REPO_URL=${APK_REPO_URL}" --build-arg "APK_FALLBACK_URL=${APK_FALLBACK_URL}")
  if [[ "${parallel_flag}" == "true" && "${parallel_limit}" -gt 1 ]]; then
    opts+=(--parallel)
  fi
  if [[ -n "${BUILD_FLAG}" ]]; then
    opts+=("${BUILD_FLAG}")
  fi
  local cmd=("${COMPOSE_CMD[@]}" "${COMPOSE_FILE_ARGS[@]}" "${COMPOSE_ENV_ARGS[@]}" build "${opts[@]}")
  if [[ ${#BUILD_SERVICES[@]} -gt 0 ]]; then
    cmd+=("${BUILD_SERVICES[@]}")
  fi
  log_info "Running: COMPOSE_PARALLEL_LIMIT=${parallel_limit} ${cmd[*]}"
  COMPOSE_PARALLEL_LIMIT="${parallel_limit}" "${cmd[@]}"
}

if ! run_compose_build true "${COMPOSE_PARALLEL_LIMIT}"; then
  if [[ "${COMPOSE_PARALLEL_LIMIT}" -gt 1 ]]; then
    log_warn "Parallel compose build failed (BuildKit flake). Retrying sequentially."
    if ! run_compose_build false 1; then
      log_warn "Sequential compose build also failed."
      exit 1
    fi
  else
    exit 1
  fi
fi
fi # end USE_BAKE else branch
else
  log_warn "Skipping docker compose build step (per --skip-build)."
fi

log_step "Starting services"
UP_CMD=("${COMPOSE_CMD[@]}" "${COMPOSE_FILE_ARGS[@]}" "${COMPOSE_ENV_ARGS[@]}" up "--remove-orphans")
if [[ "${DETACH_MODE}" == "true" ]]; then
  UP_CMD+=("--detach")
fi
if [[ ${#WAIT_FLAG[@]} -gt 0 ]]; then
  UP_CMD+=("${WAIT_FLAG[@]}")
fi
if [[ ${#UP_ARGS[@]} -gt 0 ]]; then
  UP_CMD+=("${UP_ARGS[@]}")
fi

run_compose_up_with_conflict_retry() {
  local up_log
  up_log="$(mktemp)"

  log_info "Running: ${UP_CMD[*]}"
  set +e
  "${UP_CMD[@]}" 2>&1 | tee "${up_log}"
  local up_status=${PIPESTATUS[0]}
  set -e

  if [[ "${up_status}" -eq 0 ]]; then
    rm -f "${up_log}"
    return 0
  fi

  # Recover once from stale compose artifacts (common after interrupted local runs).
  if grep -Eqi "already exists|is already in use|Conflict\\. The container name" "${up_log}"; then
    local down_cmd=("${COMPOSE_CMD[@]}" "${COMPOSE_FILE_ARGS[@]}" "${COMPOSE_ENV_ARGS[@]}" down "--remove-orphans")
    log_warn "Compose up failed due to stale Docker resources; cleaning project resources and retrying once."
    log_info "Running: ${down_cmd[*]}"
    "${down_cmd[@]}"
    log_info "Retrying: ${UP_CMD[*]}"
    set +e
    "${UP_CMD[@]}" 2>&1 | tee "${up_log}"
    up_status=${PIPESTATUS[0]}
    set -e
  fi

  rm -f "${up_log}"
  return ${up_status}
}

run_compose_up_with_conflict_retry

API_PORT="${API_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
STREAMER_PORT="${STREAMER_PORT:-8100}"
RELAYER_PORT="${RELAYER_PORT:-8088}"
HEDGER_API_PORT="${HEDGER_API_PORT:-8090}"
POSTGRES_URI="${POSTGRES_URI:-postgres://market_admin:<REDACTED>@localhost:5432/reveal_market}"
REDIS_CMD="${REDIS_CMD:-redis-cli -h localhost -p 6379}"

PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"
GRAFANA_PORT="${GRAFANA_PORT:-3001}"
PROVER_PORT="${PROVER_PORT:-8085}"
WORKER_METRICS_PORT="${WORKER_METRICS_PORT:-9100}"

cat <<EOF
------------------------------------------------------------
Stack ready. Useful URLs:

  Apps:
    • Frontend:             http://localhost:${FRONTEND_PORT}
    • API docs:             http://localhost:${API_PORT}/docs
    • API health:           http://localhost:${API_PORT}/healthz
    • API heartbeats:       http://localhost:${API_PORT}/healthz/heartbeats
    • Streamer health:      http://localhost:${STREAMER_PORT}/healthz
    • Streamer FX feed:     http://localhost:${STREAMER_PORT}/fx/zen-usd
    • Streamer history:     http://localhost:${STREAMER_PORT}/history?market_id=...&outcome=0

  Services:
    • Relayer health:       http://localhost:${RELAYER_PORT}/healthz
    • Hedger health:        http://localhost:${HEDGER_API_PORT}/healthz
    • Prover health:        http://localhost:${PROVER_PORT}/healthz

  Monitoring:
    • Grafana dashboards:   http://localhost:${GRAFANA_PORT}
    • Prometheus UI:        http://localhost:${PROMETHEUS_PORT}
    • Prometheus targets:   http://localhost:${PROMETHEUS_PORT}/targets
    • Prometheus alerts:    http://localhost:${PROMETHEUS_PORT}/alerts

  Metrics endpoints:
    • API metrics:          http://localhost:${API_PORT}/metrics
    • Worker metrics:       http://localhost:${WORKER_METRICS_PORT}/metrics
    • Streamer metrics:     http://localhost:${STREAMER_PORT}/metrics
    • Hedger metrics:       http://localhost:${HEDGER_API_PORT}/metrics
    • Relayer metrics:      http://localhost:${RELAYER_PORT}/metrics
    • Prover metrics:       http://localhost:${PROVER_PORT}/metrics

  Datastores:
    • Postgres (psql):      postgres://market_admin:<REDACTED>@localhost:5432/reveal_market
    • Redis (CLI):          redis-cli -h localhost -p 6379
------------------------------------------------------------
EOF

# Emit a quick health snapshot when supported (Compose v2+).
if "${COMPOSE_CMD[@]}" ps --help 2>/dev/null | grep -q -- "--format"; then
  log_step "Service status"
  HEALTH_SUMMARY_SCRIPT="$(cat <<'PY'
import json
import sys

raw = sys.stdin.read().strip()
if not raw:
    sys.exit(0)

items: list[dict] = []
# docker compose ps --format json can emit a JSON array or one object per line,
# depending on the version. Parse both shapes defensively.
try:
    data = json.loads(raw)
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        candidates = []
        for key in ("services", "containers"):
            val = data.get(key)
            if isinstance(val, list):
                candidates.extend(val)
            elif isinstance(val, dict):
                candidates.extend(val.values())
        items = candidates or [data]
except Exception:
    for line in raw.splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            items.append(obj)

for svc in items:
    if not isinstance(svc, dict):
        continue
    print(f"{svc.get('Name', ''):30s} state={svc.get('State')} health={svc.get('Health')}")
PY
)"
  "${COMPOSE_CMD[@]}" "${COMPOSE_ENV_ARGS[@]}" ps --format json | python3 -c "${HEALTH_SUMMARY_SCRIPT}"
fi

cat <<EOF
✅ Services started successfully.
   Compose command: ${COMPOSE_CMD[*]} ${COMPOSE_FILE_ARGS[*]} ${COMPOSE_ENV_ARGS[*]} ${UP_ARGS[*]}
EOF
