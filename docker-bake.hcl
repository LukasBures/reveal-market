# docker-bake.hcl — Parallel multi-service builds with shared base layers.
#
# Usage:
#   docker buildx bake                  # Build all services
#   docker buildx bake python           # Build only Python services
#   docker buildx bake api worker       # Build specific targets
#   docker buildx bake --print          # Inspect resolved build config
#
# How it works:
#   1. python-base and python-runtime are built first (shared builder/runtime bases)
#   2. All 5 Python services build in parallel, inheriting the shared bases
#   3. Frontend and prover build in parallel (independent of Python bases)
#
# The `contexts` map lets each service Dockerfile use `FROM python-base` and
# `FROM python-runtime` which resolve to the targets defined here — not to
# Docker Hub images.

# ---------------------------------------------------------------------------
# Variables — override via env or CLI: docker buildx bake --set '*.args.UV_BUILDER_IMAGE=...'
# ---------------------------------------------------------------------------

variable "UV_BUILDER_IMAGE" {
  default = "ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58"
}

variable "PYTHON_RUNTIME_IMAGE" {
  default = "python:3.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c"
}

variable "NODE_IMAGE" {
  default = "node:20-alpine@sha256:09e2b3d9726018aecf269bd35325f46bf75046a643a66d28360ec71132750ec8"
}

variable "GOLANG_IMAGE" {
  default = "golang:1.24-alpine@sha256:8bee1901f1e530bfb4a7850aa7a479d17ae3a18beb6e09064ed54cfd245b7191"
}

# Frontend build-time env vars (passed as build args).
variable "NEXT_PUBLIC_API_BASE_URL" { default = "http://localhost:8000" }
variable "NEXT_PUBLIC_PRICE_STREAMER_URL" { default = "http://localhost:8100" }
variable "NEXT_PUBLIC_SITE_URL" { default = "http://localhost:3000" }
variable "NEXT_PUBLIC_CHAIN_ID" { default = "26514" }
variable "NEXT_PUBLIC_CHAIN_NAME" { default = "Horizen Mainnet" }
variable "NEXT_PUBLIC_RPC_URL" { default = "https://horizen.calderachain.xyz/http" }
variable "NEXT_PUBLIC_BLOCK_EXPLORER_URL" { default = "https://horizen.calderaexplorer.xyz" }
variable "NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID" { default = "" }
variable "NEXT_PUBLIC_ZEN_TOKEN_ADDRESS" { default = "" }
variable "NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS" { default = "" }
variable "NEXT_DISABLE_MINIFY" { default = "false" }

# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

group "default" {
  targets = [
    "api", "worker", "hedger", "streamer", "relayer",
    "frontend", "prover", "caddy",
  ]
}

group "python" {
  targets = ["api", "worker", "hedger", "streamer", "relayer"]
}

# ---------------------------------------------------------------------------
# Shared base targets (built once, inherited by all Python services)
# ---------------------------------------------------------------------------

target "python-base" {
  dockerfile = "docker/python-base.Dockerfile"
  context    = "."
  args = {
    UV_BUILDER_IMAGE = UV_BUILDER_IMAGE
  }
}

target "python-runtime" {
  dockerfile = "docker/python-runtime.Dockerfile"
  context    = "."
  args = {
    PYTHON_RUNTIME_IMAGE = PYTHON_RUNTIME_IMAGE
  }
}

# ---------------------------------------------------------------------------
# Python services — all inherit python-base (builder) and python-runtime
# ---------------------------------------------------------------------------

target "api" {
  dockerfile = "docker/api/Dockerfile"
  context    = "."
  contexts = {
    "python-base"    = "target:python-base"
    "python-runtime" = "target:python-runtime"
  }
  tags = ["reveal-market-api:latest"]
}

target "worker" {
  dockerfile = "docker/worker/Dockerfile"
  context    = "."
  contexts = {
    "python-base"    = "target:python-base"
    "python-runtime" = "target:python-runtime"
  }
  tags = ["reveal-market-worker:latest"]
}

target "hedger" {
  dockerfile = "docker/hedger/Dockerfile"
  context    = "."
  contexts = {
    "python-base"    = "target:python-base"
    "python-runtime" = "target:python-runtime"
  }
  tags = ["reveal-market-hedger:latest"]
}

target "streamer" {
  dockerfile = "docker/streamer/Dockerfile"
  context    = "."
  contexts = {
    "python-base"    = "target:python-base"
    "python-runtime" = "target:python-runtime"
  }
  tags = ["reveal-market-streamer:latest"]
}

target "relayer" {
  dockerfile = "docker/relayer/Dockerfile"
  context    = "."
  contexts = {
    "python-base"    = "target:python-base"
    "python-runtime" = "target:python-runtime"
  }
  tags = ["reveal-market-relayer:latest"]
}

# ---------------------------------------------------------------------------
# Non-Python services (independent builds, run in parallel with Python group)
# ---------------------------------------------------------------------------

target "frontend" {
  dockerfile = "docker/frontend/Dockerfile"
  context    = "."
  args = {
    NODE_IMAGE                           = NODE_IMAGE
    NEXT_PUBLIC_API_BASE_URL             = NEXT_PUBLIC_API_BASE_URL
    NEXT_PUBLIC_PRICE_STREAMER_URL       = NEXT_PUBLIC_PRICE_STREAMER_URL
    NEXT_PUBLIC_SITE_URL                 = NEXT_PUBLIC_SITE_URL
    NEXT_PUBLIC_CHAIN_ID                 = NEXT_PUBLIC_CHAIN_ID
    NEXT_PUBLIC_CHAIN_NAME               = NEXT_PUBLIC_CHAIN_NAME
    NEXT_PUBLIC_RPC_URL                  = NEXT_PUBLIC_RPC_URL
    NEXT_PUBLIC_BLOCK_EXPLORER_URL       = NEXT_PUBLIC_BLOCK_EXPLORER_URL
    NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID = NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID
    NEXT_PUBLIC_ZEN_TOKEN_ADDRESS        = NEXT_PUBLIC_ZEN_TOKEN_ADDRESS
    NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS   = NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS
    NEXT_DISABLE_MINIFY                  = NEXT_DISABLE_MINIFY
  }
  tags = ["reveal-market-frontend:latest"]
}

target "prover" {
  dockerfile = "docker/prover/Dockerfile"
  context    = "."
  args = {
    GOLANG_IMAGE = GOLANG_IMAGE
    NODE_IMAGE   = NODE_IMAGE
  }
  tags = ["reveal-market-prover:latest"]
}

target "caddy" {
  dockerfile = "Dockerfile"
  context    = "./docker/caddy"
  tags = ["reveal-market-caddy:latest"]
}
