# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock /app/
RUN pip install --no-cache-dir uv==0.1.47
RUN uv sync --frozen --no-install-project --extra dev

COPY app /app/app

EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -m app.healthcheck

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
