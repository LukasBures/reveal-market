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

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ENV_FILE="${ROOT_DIR}/.env"
ENV_FILE="${ENV_FILE:-${DEFAULT_ENV_FILE}}"
SKIP_PROOVER_CHECK="${SKIP_PROOVER_CHECK:-false}"
PROOVER_BUILD_DIR="${ROOT_DIR}/proover/circuits/build"
PROOVER_REQUIRED_FILES=(
  "settlement_js/generate_witness.js"
  "settlement_js/settlement.wasm"
  "settlement_final.zkey"
)
DEFAULT_CADDY_FILE="${ROOT_DIR}/docker/caddy/Caddyfile"
CADDY_DOMAIN="${CADDY_DOMAIN:-revealmarket.xyz}"
CADDY_ACME_EMAIL="${CADDY_ACME_EMAIL:-infra@revealmarket.xyz}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required to deploy the stack" >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=("docker" "compose")
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=("docker-compose")
else
  echo "docker compose or docker-compose is required" >&2
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
  --skip-proover-check   Skip Groth16 artifact validation (not recommended).
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

check_proover_artifacts() {
  if [[ "${SKIP_PROOVER_CHECK}" == "true" ]]; then
    echo "Skipping Groth16 prover artifact validation (per flag)."
    return
  fi

  local missing=()
  for rel_path in "${PROOVER_REQUIRED_FILES[@]}"; do
    local full_path="${PROOVER_BUILD_DIR}/${rel_path}"
    if [[ ! -f "${full_path}" ]]; then
      missing+=("${rel_path}")
    fi
  done

  if (( ${#missing[@]} > 0 )); then
    echo "Groth16 artifacts missing; running proover/circuits/generate_keys.sh ..."
    (cd "${ROOT_DIR}/proover/circuits" && bash generate_keys.sh)
  fi
}

ensure_caddyfile() {
  local target="${DEFAULT_CADDY_FILE}"
  local target_dir
  target_dir="$(dirname "${target}")"
  mkdir -p "${target_dir}"
  local desired
  read -r -d '' desired <<EOF || true
{
  admin off
  grace_period 5s
  servers :443 {
    protocols h1 h2 h3
    max_header_size 32kb
    read_timeout 30s
    write_timeout 30s
    idle_timeout 120s
    request_body {
      max_size 20MB
    }
  }
  servers :80 {
    protocols h1 h2
    read_timeout 15s
    write_timeout 15s
    idle_timeout 60s
  }
}

${CADDY_DOMAIN} {
  encode zstd gzip
  tls {
    protocols tls1.2 tls1.3
    curves x25519 secp521r1 secp384r1
    issuer acme {
      email ${CADDY_ACME_EMAIL}
    }
  }
  header {
    Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
    X-Content-Type-Options "nosniff"
    Referrer-Policy "strict-origin-when-cross-origin"
    Permissions-Policy "accelerometer=(), autoplay=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()"
    X-Frame-Options "DENY"
    Cache-Control "public, max-age=60"
    -Server
  }
  log {
    output stdout
    format single_field "{ts} | {level} | caddy.access | {request>remote_ip} | {request>method} {request>uri} {response>status} {size}B {duration}"
  }
  reverse_proxy frontend:3000 {
    header_up X-Forwarded-Proto {scheme}
    header_up X-Forwarded-Host {host}
    header_up X-Real-IP {remote_host}
    trusted_proxies private_ranges
    transport http {
      versions h1 h2c
      keepalive_idle_conns 128
      keepalive_interval 60s
      read_buffer 4MiB
      write_buffer 4MiB
    }
  }
}

www.${CADDY_DOMAIN} {
  encode zstd gzip
  tls {
    protocols tls1.2 tls1.3
  }
  redir https://${CADDY_DOMAIN}{uri} 308
}
EOF

  if [[ ! -f "${target}" || "$(cat "${target}")" != "${desired}" ]]; then
    echo "Writing Caddyfile for ${CADDY_DOMAIN} -> frontend:3000"
    printf "%s\n" "${desired}" > "${target}"
  fi
}

PARALLEL_BUILDS="$(calc_parallel_builds)"
WAIT_FLAG=()
if supports_wait_flag; then
  WAIT_FLAG+=("--wait")
fi

export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
export COMPOSE_PARALLEL_LIMIT="${PARALLEL_BUILDS}"

RUN_BUILD="true"
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
    --skip-proover-check)
      SKIP_PROOVER_CHECK="true"
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

check_env_file
check_proover_artifacts
ensure_caddyfile

echo "Validating docker compose files..."
"${COMPOSE_CMD[@]}" config >/dev/null

if [[ "${RUN_BUILD}" == "true" ]]; then
  echo "Building Docker images (cached layers, pulling latest bases, parallel=${COMPOSE_PARALLEL_LIMIT})..."
  "${COMPOSE_CMD[@]}" build --parallel --pull
else
  echo "Skipping docker compose build step (per --skip-build)."
fi

echo "Starting services in detached mode..."
UP_CMD=("${COMPOSE_CMD[@]}" up "-d" "--remove-orphans" "${WAIT_FLAG[@]}")
if [[ ${#UP_ARGS[@]} -gt 0 ]]; then
  UP_CMD+=("${UP_ARGS[@]}")
fi
"${UP_CMD[@]}"

"${COMPOSE_CMD[@]}" ps

echo "Deployment complete."
DEFAULT_CADDY_FILE="${ROOT_DIR}/docker/caddy/Caddyfile"
