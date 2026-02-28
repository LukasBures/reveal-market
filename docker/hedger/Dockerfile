# syntax=docker/dockerfile:1.4

ARG BUILDKIT_INLINE_CACHE=1
# Pinned 2026-02-27
ARG UV_BUILDER_IMAGE=ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58
ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c
ARG SERVICE_DIR=hedger
ARG SHARED_DIR=backend/shared

# =============================================================================
# Stage 1: Builder — install runtime deps with uv (no dev extras)
# =============================================================================
FROM ${UV_BUILDER_IMAGE} AS builder
ARG SERVICE_DIR=hedger

WORKDIR /hedger

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    build-essential \
    libpq-dev \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

COPY ${SERVICE_DIR}/pyproject.toml ./pyproject.toml
COPY ${SERVICE_DIR}/uv.lock ./uv.lock

RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev --frozen --no-install-project

# =============================================================================
# Stage 2: Test — install dev extras and run pytest
# =============================================================================
FROM builder AS test
ARG SERVICE_DIR=hedger
ARG SHARED_DIR=backend/shared

RUN --mount=type=cache,target=/root/.cache/uv uv sync --extra dev --frozen

COPY ${SERVICE_DIR}/app ./app
COPY ${SERVICE_DIR}/run.py ./run.py
COPY ${SERVICE_DIR}/tests ./tests
COPY ${SHARED_DIR} ./shared

CMD ["uv", "run", "--frozen", "pytest", "-q"]

# =============================================================================
# Stage 3: Runtime — slim image with synced venv + source
# =============================================================================
FROM ${PYTHON_RUNTIME_IMAGE} AS hedger
ARG SERVICE_DIR=hedger
ARG SHARED_DIR=backend/shared

WORKDIR /hedger

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/hedger \
    PATH="/hedger/.venv/bin:$PATH" \
    HEDGER_LOG_LEVEL=INFO

RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libpq5 \
 && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY --from=builder /hedger/.venv ./.venv

RUN useradd --create-home hedgeruser
USER hedgeruser

COPY --chown=hedgeruser:hedgeruser ${SHARED_DIR} ./shared
COPY --chown=hedgeruser:hedgeruser ${SERVICE_DIR}/app ./app
COPY --chown=hedgeruser:hedgeruser ${SERVICE_DIR}/run.py ./run.py

HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8090/healthz >/dev/null || exit 1

CMD ["python", "run.py"]
