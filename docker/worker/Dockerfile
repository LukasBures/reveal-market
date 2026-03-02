# syntax=docker/dockerfile:1.4

# Pinned 2026-02-27
ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c
ARG SERVICE_DIR=backend/worker
ARG SHARED_DIR=backend/shared
ARG MIGRATIONS_DIR=backend/migrations
ARG APP_USER=workeruser
ARG APP_GROUP=workeruser

# =============================================================================
# Stage 1: Builder — install runtime deps with uv (no dev extras)
# =============================================================================
FROM python-base AS builder
ARG SERVICE_DIR=backend/worker

WORKDIR /worker

COPY ${SERVICE_DIR}/pyproject.toml ./pyproject.toml
COPY ${SERVICE_DIR}/uv.lock ./uv.lock

RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev --frozen --no-install-project

# =============================================================================
# Stage 2: Test — pull in dev dependencies and include full source for pytest
# =============================================================================
FROM builder AS test
ARG SERVICE_DIR=backend/worker
ARG SHARED_DIR=backend/shared
ARG MIGRATIONS_DIR=backend/migrations

RUN --mount=type=cache,target=/root/.cache/uv uv sync --extra dev --frozen

COPY ${SHARED_DIR} ./shared
COPY ${MIGRATIONS_DIR} ./migrations
COPY ${SERVICE_DIR}/app ./app
COPY ${SERVICE_DIR}/run.py ./run.py
COPY ${SERVICE_DIR}/tests ./tests

CMD ["uv", "run", "--frozen", "pytest", "-q"]

# =============================================================================
# Stage 3: Runtime — slim image with synced venv + source
# =============================================================================
FROM python-runtime AS worker
ARG SERVICE_DIR=backend/worker
ARG SHARED_DIR=backend/shared
ARG MIGRATIONS_DIR=backend/migrations
ARG APP_USER=workeruser
ARG APP_GROUP=workeruser

WORKDIR /worker

ENV PYTHONPATH=/worker \
    PATH="/worker/.venv/bin:$PATH"

COPY --from=builder --link /worker/.venv ./.venv

RUN id -u "${APP_USER}" >/dev/null 2>&1 || (groupadd -r "${APP_GROUP}" && useradd --create-home -r -g "${APP_GROUP}" "${APP_USER}")
USER ${APP_USER}

COPY --chown=workeruser:workeruser ${SHARED_DIR} ./shared
COPY --chown=workeruser:workeruser ${SERVICE_DIR}/app ./app
COPY --chown=workeruser:workeruser ${SERVICE_DIR}/run.py ./run.py
COPY --chown=workeruser:workeruser ${MIGRATIONS_DIR} ./migrations
# Include contract error selectors for backend decoding utilities.
COPY --chown=workeruser:workeruser contracts/cache /contracts/cache

HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 \
  CMD python -m app.healthcheck

CMD ["python", "run.py"]
