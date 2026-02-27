# syntax=docker/dockerfile:1

# Pinned 2026-02-27
FROM python:3.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock /app/
RUN pip install --no-cache-dir uv==0.1.47
RUN uv sync --frozen --no-install-project --no-dev

COPY app /app/app

# Drop privileges to a dedicated user.
ARG APP_USER=streamer
ARG APP_GROUP=streamer
RUN id -u "${APP_USER}" >/dev/null 2>&1 || (groupadd -r "${APP_GROUP}" && useradd --create-home -r -g "${APP_GROUP}" "${APP_USER}")
RUN chown -R "${APP_USER}:${APP_GROUP}" /app
USER ${APP_USER}

EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -m app.healthcheck

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
