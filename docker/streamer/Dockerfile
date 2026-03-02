# syntax=docker/dockerfile:1.4

# Pinned 2026-02-27
ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c
ARG APP_USER=streamer
ARG APP_GROUP=streamer

# =============================================================================
# Stage 1: Builder — install runtime deps with uv (no dev extras)
# =============================================================================
FROM python-base AS builder
WORKDIR /app

COPY streamer/pyproject.toml streamer/uv.lock /app/

RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev --frozen --no-install-project

COPY streamer/README.md /app/README.md
COPY streamer/app /app/app

# =============================================================================
# Stage 2: Test — install dev extras and run pytest
# =============================================================================
FROM builder AS test

RUN --mount=type=cache,target=/root/.cache/uv uv sync --extra dev --frozen

COPY streamer/tests /app/tests

CMD ["uv", "run", "--frozen", "pytest", "-q"]

# =============================================================================
# Stage 3: Runtime — slim image with synced venv + source
# =============================================================================
FROM python-runtime AS streamer
ARG APP_USER
ARG APP_GROUP

WORKDIR /app

ENV PYTHONPATH=/app \
    PATH="/app/.venv/bin:$PATH"

COPY --from=builder --link /app/.venv ./.venv
COPY --from=builder --link /app/app /app/app
COPY backend/shared /app/shared

RUN id -u "${APP_USER}" >/dev/null 2>&1 || (groupadd -r "${APP_GROUP}" && useradd --create-home -r -g "${APP_GROUP}" "${APP_USER}")
USER ${APP_USER}

EXPOSE 8100

HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=3 \
  CMD python -m app.healthcheck

CMD ["/app/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1"]
