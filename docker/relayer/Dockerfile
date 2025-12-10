## syntax=docker/dockerfile:1.4
ARG UV_BUILDER_IMAGE=ghcr.io/astral-sh/uv:python3.12-bookworm-slim
ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim
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

COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app/src ./src

RUN id -u "${APP_USER}" >/dev/null 2>&1 || (groupadd -r "${APP_GROUP}" && useradd --create-home -r -g "${APP_GROUP}" "${APP_USER}")
USER ${APP_USER}

CMD ["/bin/sh", "-c", "/app/.venv/bin/python -m uvicorn relayer.main:app --host \"${RELAYER_HOST}\" --port \"${RELAYER_PORT}\""]
