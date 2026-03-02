# syntax=docker/dockerfile:1.4
# =============================================================================
# Shared builder base for all Python services (api, worker, hedger, streamer,
# relayer).  Installs the union of build-time system dependencies so individual
# service Dockerfiles only need to COPY pyproject.toml + uv sync.
#
# Built automatically by docker-bake.hcl and consumed via:
#   FROM python-base AS builder
# =============================================================================

# Pinned 2026-02-27
ARG UV_BUILDER_IMAGE=ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58

FROM ${UV_BUILDER_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Union of build deps across all Python services:
#   build-essential + gcc  — C compiler toolchain (greenlet, asyncpg wheels)
#   libpq-dev              — PostgreSQL client headers (psycopg2)
#   libffi-dev + libssl-dev + openssl — FFI + SSL headers (streamer crypto deps)
#   curl + ca-certificates — health checks, TLS root certs
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update -qq \
 && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    curl \
    ca-certificates \
    libpq-dev \
    libffi-dev \
    libssl-dev \
    openssl
