# syntax=docker/dockerfile:1.4
# =============================================================================
# Shared runtime base for all Python services.  Contains only the runtime C
# libraries (no compilers) and common utilities needed by every service.
#
# Built automatically by docker-bake.hcl and consumed via:
#   FROM python-runtime AS <service>
# =============================================================================

# Pinned 2026-02-27
ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c

FROM ${PYTHON_RUNTIME_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Runtime-only libraries (no compilers):
#   libpq5          — PostgreSQL client library (psycopg2 / asyncpg runtime)
#   ca-certificates — TLS root certificates
#   curl            — health check probes
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update -qq \
 && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libpq5
