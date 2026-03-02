# syntax=docker/dockerfile:1.4

# Pinned 2026-02-27
ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c
ARG SERVICE_DIR=backend/api
ARG SHARED_DIR=backend/shared
ARG MIGRATIONS_DIR=backend/migrations
ARG APP_USER=appuser
ARG APP_GROUP=appuser

# =============================================================================
# Stage 1: Builder — install runtime deps with uv (no dev extras)
# =============================================================================
FROM python-base AS builder
ARG SERVICE_DIR=backend/api

WORKDIR /app

COPY ${SERVICE_DIR}/pyproject.toml ./pyproject.toml
COPY ${SERVICE_DIR}/uv.lock ./uv.lock

RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev --frozen --no-install-project

# =============================================================================
# Stage 2: Test — include dev dependencies + source for pytest
# =============================================================================
FROM builder AS test
ARG SERVICE_DIR=backend/api
ARG SHARED_DIR=backend/shared
ARG MIGRATIONS_DIR=backend/migrations

RUN --mount=type=cache,target=/root/.cache/uv uv sync --extra dev --frozen

COPY ${SHARED_DIR} ./shared
COPY ${MIGRATIONS_DIR} ./migrations
COPY ${SERVICE_DIR}/app ./app
COPY ${SERVICE_DIR}/tests ./tests

CMD ["uv", "run", "--frozen", "pytest", "-q"]

# =============================================================================
# Stage 3: Runtime — minimal image with synced venv and source
# =============================================================================
FROM python-runtime AS api
ARG SERVICE_DIR=backend/api
ARG SHARED_DIR=backend/shared
ARG MIGRATIONS_DIR=backend/migrations
ARG APP_USER=appuser
ARG APP_GROUP=appuser

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH"

COPY --from=builder --link /app/.venv ./.venv

# Ensure runtime user/group exist even if image lacks defaults.
RUN id -u "${APP_USER}" >/dev/null 2>&1 || (groupadd -r "${APP_GROUP}" && useradd --create-home -r -g "${APP_GROUP}" "${APP_USER}")
USER ${APP_USER}

COPY --chown=appuser:appuser ${SHARED_DIR} ./shared
COPY --chown=appuser:appuser ${SERVICE_DIR}/app ./app
COPY --chown=appuser:appuser ${SERVICE_DIR}/run.py ./run.py
COPY --chown=appuser:appuser ${MIGRATIONS_DIR} ./migrations
# Include contract error selectors for backend decoding utilities.
COPY --chown=appuser:appuser contracts/cache /contracts/cache

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=3 \
  CMD curl -fsS http://localhost:8000/live || exit 1

CMD ["python", "run.py"]
