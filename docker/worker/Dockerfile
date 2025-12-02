# syntax=docker/dockerfile:1.4

ARG BUILDKIT_INLINE_CACHE=1
ARG UV_BUILDER_IMAGE=ghcr.io/astral-sh/uv:python3.12-bookworm-slim
ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim
ARG SERVICE_DIR=backend/worker
ARG SHARED_DIR=backend/shared
ARG MIGRATIONS_DIR=backend/migrations

# =============================================================================
# Stage 1: Builder — install runtime deps with uv (no dev extras)
# =============================================================================
FROM ${UV_BUILDER_IMAGE} AS builder
ARG SERVICE_DIR=backend/worker
ARG SHARED_DIR=backend/shared
ARG MIGRATIONS_DIR=backend/migrations

WORKDIR /worker

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

RUN uv sync --no-dev --frozen --no-install-project

# =============================================================================
# Stage 2: Test — pull in dev dependencies and include full source for pytest
# =============================================================================
FROM builder AS test
ARG SERVICE_DIR=backend/worker
ARG SHARED_DIR=backend/shared
ARG MIGRATIONS_DIR=backend/migrations

RUN uv sync --extra dev --frozen

COPY ${SERVICE_DIR}/app ./app
COPY ${SERVICE_DIR}/run.py ./run.py
COPY ${SERVICE_DIR}/tests ./tests
COPY ${SHARED_DIR} ./shared
COPY ${MIGRATIONS_DIR} ./migrations

CMD ["uv", "run", "--frozen", "pytest", "-q"]

# =============================================================================
# Stage 3: Runtime — slim image with synced venv + source
# =============================================================================
FROM ${PYTHON_RUNTIME_IMAGE} AS worker
ARG SERVICE_DIR=backend/worker
ARG SHARED_DIR=backend/shared
ARG MIGRATIONS_DIR=backend/migrations

WORKDIR /worker

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/worker \
    PATH="/worker/.venv/bin:$PATH"

RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libpq5 \
 && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY --from=builder /worker/.venv ./.venv

RUN useradd --create-home workeruser
USER workeruser

COPY --chown=workeruser:workeruser ${SHARED_DIR} ./shared
COPY --chown=workeruser:workeruser ${SERVICE_DIR}/app ./app
COPY --chown=workeruser:workeruser ${SERVICE_DIR}/run.py ./run.py
COPY --chown=workeruser:workeruser ${MIGRATIONS_DIR} ./migrations
# Include contract error selectors for backend decoding utilities.
COPY --chown=workeruser:workeruser contracts/cache /contracts/cache

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -m app.healthcheck

CMD ["python", "run.py"]
