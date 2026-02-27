## syntax=docker/dockerfile:1.4
# Pinned 2026-02-27
ARG UV_BUILDER_IMAGE=ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58
ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c
ARG RELAYER_DIR=relayer
ARG APP_USER=relayeruser
ARG APP_GROUP=relayeruser

# Stage 1: builder installs uv + dependencies into a venv
FROM ${UV_BUILDER_IMAGE} AS builder
ARG RELAYER_DIR

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends build-essential gcc curl ca-certificates \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

COPY ${RELAYER_DIR}/pyproject.toml ${RELAYER_DIR}/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev --frozen --no-install-project

COPY ${RELAYER_DIR}/src ./src

# Stage 2: runtime copies the venv and source, drops build tooling
FROM ${PYTHON_RUNTIME_IMAGE} AS relayer
ARG APP_USER
ARG APP_GROUP

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:$PATH" \
    RELAYER_HOST=0.0.0.0 \
    RELAYER_PORT=8088

WORKDIR /app

RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN id -u "${APP_USER}" >/dev/null 2>&1 || (groupadd -r "${APP_GROUP}" && useradd --create-home -r -g "${APP_GROUP}" "${APP_USER}")

COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app/src ./src

RUN chown -R ${APP_USER}:${APP_GROUP} /app
USER ${APP_USER}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${RELAYER_PORT:-8088}/healthz')"

CMD ["/bin/sh", "-c", "/app/.venv/bin/python -m uvicorn relayer.main:app --host \"${RELAYER_HOST}\" --port \"${RELAYER_PORT}\""]
