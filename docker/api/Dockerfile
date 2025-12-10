# syntax=docker/dockerfile:1.4

ARG BUILDKIT_INLINE_CACHE=1
ARG UV_BUILDER_IMAGE=ghcr.io/astral-sh/uv:python3.12-bookworm-slim
ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim
ARG SERVICE_DIR=backend/api
ARG SHARED_DIR=backend/shared
ARG MIGRATIONS_DIR=backend/migrations
ARG APP_USER=appuser
ARG APP_GROUP=appuser

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
    build-essential \
    libpq-dev \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

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
ARG APP_USER=appuser
ARG APP_GROUP=appuser

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libpq5 \
    tini \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY --from=builder /app/.venv ./.venv

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

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/healthz || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "run.py"]
