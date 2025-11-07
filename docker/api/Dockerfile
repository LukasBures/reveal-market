FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3

WORKDIR /app

# Install build tooling + Poetry only in builder image
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "poetry==${POETRY_VERSION}"

# Copy dependency metadata and shared libs to keep cache hits high
COPY backend/api/pyproject.toml ./pyproject.toml
COPY backend/shared ./shared

# Export runtime deps and pre-install wheels so runtime stays slim
RUN poetry export --only main --format requirements.txt --output /tmp/requirements.txt --without-hashes \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm -rf /tmp/requirements.txt

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODE=prod

WORKDIR /app

# Runtime dependencies only (curl + libpq client)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy already-installed dependencies from builder layer
COPY --from=builder /usr/local/lib/python3.13 /usr/local/lib/python3.13
COPY --from=builder /usr/local/bin /usr/local/bin

# Drop privileges
RUN useradd --create-home appuser
USER appuser

# Copy application code
COPY --chown=appuser:appuser backend/shared ./shared
COPY --chown=appuser:appuser backend/api/app ./app
COPY --chown=appuser:appuser backend/api/run.py ./run.py
COPY --chown=appuser:appuser backend/migrations ./migrations

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["python", "run.py"]
