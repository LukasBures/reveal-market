FROM python:3.13-slim AS builder

# Builder stage mirrors the API image so shared libs resolve consistently.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3 \
    VENV_PATH=/opt/venv

WORKDIR /worker

# Install compilers + Poetry, then capture dependencies inside /opt/venv.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir "poetry==${POETRY_VERSION}" \
    && python -m venv "${VENV_PATH}" \
    && "${VENV_PATH}/bin/pip" install --no-cache-dir --upgrade pip setuptools wheel

# Bring in dependency metadata only to improve cache re-use
COPY backend/worker/pyproject.toml ./pyproject.toml
COPY backend/worker/poetry.lock ./poetry.lock

# Export locked deps -> requirements, install wheels inside the venv, drop temp file
RUN poetry export --only main --format requirements.txt --output /tmp/requirements.txt --without-hashes \
    && "${VENV_PATH}/bin/pip" install --no-cache-dir -r /tmp/requirements.txt \
    && rm -rf /tmp/requirements.txt

FROM python:3.13-slim AS runtime

# Runtime defaults keep MODE=prod while leaving PYTHONPATH at /worker so
# legacy imports still work. PATH ensures the venv shims win.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/worker \
    MODE=prod \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /worker

# Only install runtime libs (no compilers) to shrink the final image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy preinstalled dependencies from builder venv
COPY --from=builder /opt/venv /opt/venv

# Non-root user for runtime
RUN useradd --create-home workeruser
USER workeruser

# Copy worker code + migrations so the worker can run maintenance tasks.
COPY --chown=workeruser:workeruser backend/shared ./shared
COPY --chown=workeruser:workeruser backend/worker/app ./app
COPY --chown=workeruser:workeruser backend/worker/run.py ./run.py
COPY --chown=workeruser:workeruser backend/migrations ./migrations

# Worker ships a lightweight health module that verifies DB connectivity; reuse
# it for Docker health checks to avoid duplicating shell logic.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -m app.healthcheck

CMD ["python", "run.py"]
