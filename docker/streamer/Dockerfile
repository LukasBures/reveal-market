# syntax=docker/dockerfile:1.4

ARG BUILDKIT_INLINE_CACHE=1
# Pinned 2026-02-27
ARG UV_BUILDER_IMAGE=ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58
ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c
ARG APP_USER=streamer
ARG APP_GROUP=streamer

FROM ${UV_BUILDER_IMAGE} AS builder
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends curl ca-certificates build-essential libffi-dev openssl libssl-dev \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

COPY streamer/pyproject.toml streamer/uv.lock /app/

RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev --frozen --no-install-project

COPY streamer/README.md /app/README.md
COPY streamer/app /app/app

FROM ${PYTHON_RUNTIME_IMAGE} AS streamer
ARG APP_USER
ARG APP_GROUP

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app/app /app/app
COPY backend/shared /app/shared

RUN id -u "${APP_USER}" >/dev/null 2>&1 || (groupadd -r "${APP_GROUP}" && useradd --create-home -r -g "${APP_GROUP}" "${APP_USER}")
USER ${APP_USER}

EXPOSE 8100

CMD ["/app/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1"]
