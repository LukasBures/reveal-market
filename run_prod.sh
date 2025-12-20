#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# run_prod.sh
# -----------------------------------------------------------------------------
# Production-friendly deploy helper.
# - Validates Docker + compose availability and ensures the env/prover artifacts exist.
# - Builds images with cache using BuildKit, always pulling the latest bases (unless --skip-build).
# - Launches docker compose in detached mode (with --wait when supported) and prints service status.
# - Designed for VPS/server usage; run CI-equivalent tests beforehand (make test / contracts/run_local.sh full / npm run build).
# - Python services rely on uv-managed deps; keep backend/api and backend/worker in sync (`uv sync --extra dev`) before CI or image builds.
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
DEFAULT_ENV_FILE="${ROOT_DIR}/.env.production"
ENV_FILE="${ENV_FILE:-${DEFAULT_ENV_FILE}}"
FRONTEND_ENV_FILE="${ROOT_DIR}/frontend/.env.production"
if [[ -f "${ENV_FILE}" ]]; then
  log_step "Seeding frontend env from ${ENV_FILE} -> ${FRONTEND_ENV_FILE}"
  cp "${ENV_FILE}" "${FRONTEND_ENV_FILE}"
fi
export ENV_FILE
export FRONTEND_ENV_FILE
SKIP_PROVER_CHECK="${SKIP_PROVER_CHECK:-false}"
PROVER_ARTIFACTS_DIR="${ROOT_DIR}/prover/artifacts"
PROVER_ARTIFACTS_SSH_KEY_PATH="${PROVER_ARTIFACTS_SSH_KEY_PATH:-}"
PROVER_BUILD_DIR="${ROOT_DIR}/prover/circuits/build"
PROVER_ARTIFACTS_BUILD_DIR="${PROVER_ARTIFACTS_DIR}/prover/circuits/build"
PROVER_ARTIFACTS_URL="${PROVER_ARTIFACTS_URL:-}"
PROVER_ARTIFACTS_SHA256="${PROVER_ARTIFACTS_SHA256:-}"
APK_REPO_URL="${APK_REPO_URL:-https://dl-cdn.alpinelinux.org/alpine}"
APK_FALLBACK_URL="${APK_FALLBACK_URL:-https://mirror.leaseweb.net/alpine}"
ALPINE_BASE_IMAGES=("caddy:2-alpine" "node:20-alpine" "python:3.12-alpine")
PROVER_REQUIRED_FILES=(
  "prover/circuits/build/settlement_js/generate_witness.js"
  "prover/circuits/build/settlement_js/settlement.wasm"
  "prover/circuits/build/settlement_final.zkey"
  "prover/circuits/build/settlement_vk.json"
  "prover/circuits/build/settlement_hashes.json"
  "prover/circuits/build/settlement_deploy.json"
  "contracts/cache/settlement-vk.json"
  "contracts/zen/cache/settlement-vk.json"
)
TARGET_CADDYFILE="${ROOT_DIR}/docker/caddy/Caddyfile"

prune_docker_artifacts() {
  log_step "Pruning unused Docker images, containers, and build cache"
  docker system prune -af >/dev/null
  docker builder prune -af >/dev/null || true
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

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=("docker" "compose")
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=("docker-compose")
else
  log_warn "docker compose or docker-compose is required"
  exit 1
fi
export COMPOSE_FILE="${ROOT_DIR}/docker-compose.yml"
COMPOSE_FILE_ARGS=(-f "${COMPOSE_FILE}")

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
  --skip-prover-check    Skip Groth16 artifact validation (not recommended).
  --prune                Run 'docker system prune -af' and 'docker builder prune -af' before building.
  -h, --help             Show this help text.
EOF
}

read_env_file_value() {
  local key="$1"
  local file="$2"
  if [[ -z "${file}" || ! -f "${file}" ]]; then
    return 0
  fi
  local line
  line="$(grep -E "^${key}=" "${file}" | tail -n 1)" || return 0
  local value="${line#${key}=}"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf "%s" "${value}"
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

list_missing_prover_files() {
  for rel_path in "${PROVER_REQUIRED_FILES[@]}"; do
    if [[ ! -s "${ROOT_DIR}/${rel_path}" ]]; then
      echo "${rel_path}"
    fi
  done
}

update_prover_artifacts_submodule() {
  if [[ ! -d "${PROVER_ARTIFACTS_DIR}" ]]; then
    return 1
  fi
  if ! command -v git >/dev/null 2>&1; then
    log_warn "git not found; ensure prover/artifacts is populated before running."
    return 1
  fi
  local submodule_env=()
  if [[ -n "${PROVER_ARTIFACTS_SSH_KEY_PATH}" ]]; then
    if [[ ! -f "${PROVER_ARTIFACTS_SSH_KEY_PATH}" ]]; then
      log_warn "Artifacts SSH key not found at ${PROVER_ARTIFACTS_SSH_KEY_PATH}; proceeding without submodule auth override."
    else
      submodule_env=(GIT_SSH_COMMAND="ssh -i ${PROVER_ARTIFACTS_SSH_KEY_PATH} -o IdentitiesOnly=yes")
    fi
  fi
  "${submodule_env[@]}" git -C "${ROOT_DIR}" submodule update --init --recursive prover/artifacts >/dev/null
}

seed_prover_from_submodule() {
  if [[ ! -d "${PROVER_ARTIFACTS_BUILD_DIR}" ]]; then
    return 1
  fi
  log_step "Seeding prover artifacts from prover/artifacts"
  rm -rf "${PROVER_BUILD_DIR}"
  mkdir -p "${ROOT_DIR}/prover/circuits"
  cp -a "${PROVER_ARTIFACTS_BUILD_DIR}" "${ROOT_DIR}/prover/circuits/"

  local cache_sources=(
    "${PROVER_ARTIFACTS_DIR}/contracts/cache/settlement-vk.json"
    "${PROVER_ARTIFACTS_DIR}/contracts/zen/cache/settlement-vk.json"
  )
  local cache_targets=(
    "${ROOT_DIR}/contracts/cache/settlement-vk.json"
    "${ROOT_DIR}/contracts/zen/cache/settlement-vk.json"
  )
  for i in "${!cache_sources[@]}"; do
    if [[ -f "${cache_sources[$i]}" ]]; then
      mkdir -p "$(dirname "${cache_targets[$i]}")"
      cp "${cache_sources[$i]}" "${cache_targets[$i]}"
    fi
  done
  return 0
}

sync_prover_from_artifacts_source() {
  if [[ ! -d "${PROVER_ARTIFACTS_BUILD_DIR}" ]]; then
    return 1
  fi
  log_step "Syncing Groth16 artifacts from prover/artifacts (source of truth)"
  rm -rf "${PROVER_BUILD_DIR}"
  mkdir -p "${ROOT_DIR}/prover/circuits"
  cp -a "${PROVER_ARTIFACTS_BUILD_DIR}" "${ROOT_DIR}/prover/circuits/"
  sync_prover_caches
  return 0
}

download_prover_artifacts() {
  if [[ -z "${PROVER_ARTIFACTS_URL}" ]]; then
    return 1
  fi
  if [[ ! -x "${ROOT_DIR}/prover/scripts/download_artifacts.sh" ]]; then
    log_warn "prover/scripts/download_artifacts.sh missing or not executable; cannot download artifacts."
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

check_prover_artifacts() {
  if [[ "${SKIP_PROVER_CHECK}" == "true" ]]; then
    log_warn "Skipping Groth16 prover artifact validation (per flag)."
    return
  fi

  sync_prover_from_artifacts_source || true
  local missing=()
  log_step "Validating prover artifacts"
  sync_prover_caches
  mapfile -t missing < <(list_missing_prover_files)
  if (( ${#missing[@]} > 0 )); then
    update_prover_artifacts_submodule || true
    seed_prover_from_submodule || true
    mapfile -t missing < <(list_missing_prover_files)
  fi
  if (( ${#missing[@]} > 0 )); then
    download_prover_artifacts || true
    mapfile -t missing < <(list_missing_prover_files)
  fi

  sync_prover_caches
  mapfile -t missing < <(list_missing_prover_files)
  if (( ${#missing[@]} > 0 )); then
    cat <<EOF
Missing prover artifacts after sync attempts:
$(printf '  - %s\n' "${missing[@]}")
Populate prover/artifacts, set PROVER_ARTIFACTS_URL/PROVER_ARTIFACTS_SHA256, or run 'bash prover/circuits/generate_keys.sh' before deploying.
EOF
    exit 1
  fi
}

check_caddyfile() {
  if [[ ! -f "${TARGET_CADDYFILE}" ]]; then
    log_warn "Missing Caddyfile at ${TARGET_CADDYFILE}"
    exit 1
  fi
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

PARALLEL_BUILDS_DEFAULT="$(calc_parallel_builds)"
PARALLEL_BUILDS="${PARALLEL_BUILDS:-${PARALLEL_BUILDS_DEFAULT}}"
WAIT_FLAG=()
if supports_wait_flag; then
  WAIT_FLAG+=("--wait")
fi
COMPOSE_ENV_ARGS=()

export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
export COMPOSE_PARALLEL_LIMIT="${PARALLEL_BUILDS}"
export APK_REPO_URL
export APK_FALLBACK_URL

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

if [[ -z "${CADDY_TLS_PROFILE:-}" ]]; then
  CADDY_TLS_PROFILE="$(read_env_file_value "CADDY_TLS_PROFILE" "${ENV_FILE}")"
fi
if [[ -z "${CADDY_TLS_PROFILE:-}" ]]; then
  CADDY_TLS_PROFILE="tls_prod"
fi
export CADDY_TLS_PROFILE

if ! command -v docker >/dev/null 2>&1; then
  log_warn "docker is required to deploy the stack"
  exit 1
fi
ensure_docker_running

check_env_file
check_prover_artifacts
check_caddyfile
check_apk_mirror
disable_next_telemetry

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
log_info "Running: ${COMPOSE_CMD[*]} ${COMPOSE_FILE_ARGS[*]} ${COMPOSE_ENV_ARGS[*]} config"
"${COMPOSE_CMD[@]}" "${COMPOSE_FILE_ARGS[@]}" "${COMPOSE_ENV_ARGS[@]}" config >/dev/null

if [[ "${RUN_BUILD}" == "true" ]]; then
  log_step "Building Docker images (cached layers, pulling latest bases, parallel=${COMPOSE_PARALLEL_LIMIT})"
  run_compose_build() {
    local parallel_flag="${1:-true}"
    local parallel_limit="${2:-${COMPOSE_PARALLEL_LIMIT}}"
    local opts=(--pull --build-arg "APK_REPO_URL=${APK_REPO_URL}" --build-arg "APK_FALLBACK_URL=${APK_FALLBACK_URL}")
    if [[ "${parallel_flag}" == "true" && "${parallel_limit}" -gt 1 ]]; then
      opts+=(--parallel)
    fi
    local cmd=("${COMPOSE_CMD[@]}" "${COMPOSE_FILE_ARGS[@]}" "${COMPOSE_ENV_ARGS[@]}" build "${opts[@]}")
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
else
  log_warn "Skipping docker compose build step (per --skip-build)."
fi

log_step "Starting services in detached mode"
UP_CMD=("${COMPOSE_CMD[@]}" "${COMPOSE_FILE_ARGS[@]}" "${COMPOSE_ENV_ARGS[@]}" up "-d" "--remove-orphans" "${WAIT_FLAG[@]}" postgres redis api worker streamer prover frontend relayer caddy)
if [[ ${#UP_ARGS[@]} -gt 0 ]]; then
  UP_CMD+=("${UP_ARGS[@]}")
fi
log_info "Running: ${UP_CMD[*]}"
"${UP_CMD[@]}"

log_step "Service status"
log_info "Running: ${COMPOSE_CMD[*]} ${COMPOSE_FILE_ARGS[*]} ${COMPOSE_ENV_ARGS[*]} ps"
"${COMPOSE_CMD[@]}" "${COMPOSE_FILE_ARGS[@]}" "${COMPOSE_ENV_ARGS[@]}" ps

# Emit a concise health summary when supported (Docker Compose v2+).
if "${COMPOSE_CMD[@]}" ps --help 2>/dev/null | grep -q -- "--format"; then
  log_step "Health summary"
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
  "${COMPOSE_CMD[@]}" "${COMPOSE_FILE_ARGS[@]}" "${COMPOSE_ENV_ARGS[@]}" ps --format json | python3 -c "${HEALTH_SUMMARY_SCRIPT}"
fi

log_step "Deployment complete"
