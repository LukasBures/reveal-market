# syntax=docker/dockerfile:1.4

# Pinned 2026-02-27
ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c
ARG RELAYER_DIR=relayer
ARG APP_USER=relayeruser
ARG APP_GROUP=relayeruser

# =============================================================================
# Stage 1: Builder — install runtime deps with uv (no dev extras)
# =============================================================================
FROM python-base AS builder
ARG RELAYER_DIR

WORKDIR /app

COPY ${RELAYER_DIR}/pyproject.toml ${RELAYER_DIR}/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev --frozen --no-install-project

COPY ${RELAYER_DIR}/src ./src

# =============================================================================
# Stage 2: Runtime — copies the venv and source, drops build tooling
# =============================================================================
FROM python-runtime AS relayer
ARG APP_USER
ARG APP_GROUP

ENV PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:$PATH" \
    RELAYER_HOST=0.0.0.0 \
    RELAYER_PORT=8088

WORKDIR /app

RUN id -u "${APP_USER}" >/dev/null 2>&1 || (groupadd -r "${APP_GROUP}" && useradd --create-home -r -g "${APP_GROUP}" "${APP_USER}")

COPY --from=builder --chown=${APP_USER}:${APP_GROUP} /app/.venv ./.venv
COPY --from=builder --chown=${APP_USER}:${APP_GROUP} /app/src ./src

USER ${APP_USER}

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${RELAYER_PORT:-8088}/healthz || exit 1

CMD ["/bin/sh", "-c", "/app/.venv/bin/python -m uvicorn relayer.main:app --host \"${RELAYER_HOST}\" --port \"${RELAYER_PORT}\""]
