FROM python:3.13-slim AS builder

# Faster Python startup + deterministic Poetry version
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3

WORKDIR /worker

# Install compilers + Poetry only in builder
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "poetry==${POETRY_VERSION}"

# Bring in dependency metadata + shared libs
COPY backend/worker/pyproject.toml ./pyproject.toml
COPY backend/shared ./shared

# Export locked deps -> requirements, install wheels, drop temp file
RUN poetry export --only main --format requirements.txt --output /tmp/requirements.txt --without-hashes
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm -rf /tmp/requirements.txt

FROM python:3.13-slim AS runtime

# Runtime defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/worker \
    MODE=prod

WORKDIR /worker

# Only install runtime libs (no compilers)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy preinstalled dependencies from builder
COPY --from=builder /usr/local/lib/python3.13 /usr/local/lib/python3.13
COPY --from=builder /usr/local/bin /usr/local/bin

# Non-root user for runtime
RUN useradd --create-home workeruser
USER workeruser

# Copy worker code
COPY --chown=workeruser:workeruser backend/shared ./shared
COPY --chown=workeruser:workeruser backend/worker/app ./app
COPY --chown=workeruser:workeruser backend/worker/run.py ./run.py

# Worker healthcheck hits Python entrypoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -m app.healthcheck

CMD ["python", "run.py"]
