# syntax=docker/dockerfile:1

ARG UV_BUILDER_IMAGE=ghcr.io/astral-sh/uv:python3.12-bookworm-slim
ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim
ARG SERVICE_DIR=backend/api
ARG SHARED_DIR=backend/shared
ARG MIGRATIONS_DIR=backend/migrations

# =============================================================================
# Stage 1: Builder — install runtime deps with uv (no dev extras)
# =============================================================================
FROM ${UV_BUILDER_IMAGE} AS builder
ARG SERVICE_DIR=backend/api
ARG SHARED_DIR=backend/shared
ARG MIGRATIONS_DIR=backend/migrations

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libpq-dev \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

COPY ${SERVICE_DIR}/pyproject.toml ./pyproject.toml
COPY ${SERVICE_DIR}/uv.lock ./uv.lock

RUN uv sync --no-dev --frozen --no-install-project

# =============================================================================
# Stage 2: Test — include dev dependencies + source for pytest
# =============================================================================
FROM builder AS test
ARG SERVICE_DIR=backend/api
ARG SHARED_DIR=backend/shared
ARG MIGRATIONS_DIR=backend/migrations

RUN uv sync --extra dev --frozen

COPY ${SERVICE_DIR}/app ./app
COPY ${SHARED_DIR} ./shared
COPY ${MIGRATIONS_DIR} ./migrations
COPY ${SERVICE_DIR}/tests ./tests

CMD ["uv", "run", "--frozen", "pytest", "-q"]

# =============================================================================
# Stage 3: Runtime — minimal image with synced venv and source
# =============================================================================
FROM ${PYTHON_RUNTIME_IMAGE} AS api
ARG SERVICE_DIR=backend/api
ARG SHARED_DIR=backend/shared
ARG MIGRATIONS_DIR=backend/migrations

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libpq5 \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY --from=builder /app/.venv /.venv

RUN useradd --create-home appuser
USER appuser

COPY --chown=appuser:appuser ${SHARED_DIR} ./shared
COPY --chown=appuser:appuser ${SERVICE_DIR}/app ./app
COPY --chown=appuser:appuser ${SERVICE_DIR}/run.py ./run.py
COPY --chown=appuser:appuser ${MIGRATIONS_DIR} ./migrations

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["python", "run.py"]
