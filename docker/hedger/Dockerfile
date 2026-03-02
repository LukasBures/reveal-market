# syntax=docker/dockerfile:1.4

# Pinned 2026-02-27
ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c
ARG SERVICE_DIR=hedger
ARG SHARED_DIR=backend/shared
ARG APP_USER=hedgeruser
ARG APP_GROUP=hedgeruser

# =============================================================================
# Stage 1: Builder — install runtime deps with uv (no dev extras)
# =============================================================================
FROM python-base AS builder
ARG SERVICE_DIR=hedger

WORKDIR /hedger

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

COPY ${SHARED_DIR} ./shared
COPY ${SERVICE_DIR}/app ./app
COPY ${SERVICE_DIR}/run.py ./run.py
COPY ${SERVICE_DIR}/tests ./tests

CMD ["uv", "run", "--frozen", "pytest", "-q"]

# =============================================================================
# Stage 3: Runtime — slim image with synced venv + source
# =============================================================================
FROM python-runtime AS hedger
ARG SERVICE_DIR=hedger
ARG SHARED_DIR=backend/shared
ARG APP_USER=hedgeruser
ARG APP_GROUP=hedgeruser

WORKDIR /hedger

ENV PYTHONPATH=/hedger \
    PATH="/hedger/.venv/bin:$PATH" \
    HEDGER_LOG_LEVEL=INFO

COPY --from=builder --link /hedger/.venv ./.venv

RUN id -u "${APP_USER}" >/dev/null 2>&1 || (groupadd -r "${APP_GROUP}" && useradd --create-home -r -g "${APP_GROUP}" "${APP_USER}")
USER ${APP_USER}

COPY --chown=hedgeruser:hedgeruser ${SHARED_DIR} ./shared
COPY --chown=hedgeruser:hedgeruser ${SERVICE_DIR}/app ./app
COPY --chown=hedgeruser:hedgeruser ${SERVICE_DIR}/run.py ./run.py

HEALTHCHECK --interval=20s --timeout=10s --start-period=45s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8090/healthz >/dev/null || exit 1

CMD ["python", "run.py"]
