FROM python:3.13-slim AS builder

# Builder image keeps full toolchain (Poetry, compilers) but produces an isolated
# virtualenv we can copy into the runtime stage so the final image stays minimal.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3 \
    VENV_PATH=/opt/venv

WORKDIR /app

# Install build tooling + Python venv for dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir "poetry==${POETRY_VERSION}" \
    && python -m venv "${VENV_PATH}" \
    && "${VENV_PATH}/bin/pip" install --no-cache-dir --upgrade pip setuptools wheel

# Only copy pyproject/lockfiles so dependency installation stays cached unless
# the dependency graph actually changes.
COPY backend/api/pyproject.toml ./pyproject.toml
COPY backend/api/poetry.lock ./poetry.lock

# Export runtime deps and pre-install wheels in the dedicated venv. This keeps
# Poetry out of the runtime image while still respecting the lock file.
RUN poetry export --only main --format requirements.txt --output /tmp/requirements.txt --without-hashes \
    && "${VENV_PATH}/bin/pip" install --no-cache-dir -r /tmp/requirements.txt \
    && rm -rf /tmp/requirements.txt

FROM python:3.13-slim AS runtime

# Runtime only needs the slim base + the copied venv. MODE + PATH configure the
# FastAPI app to boot in production mode.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODE=prod \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Runtime dependencies only (curl for healthchecks + libpq for psycopg2).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy already-installed dependencies from builder venv
COPY --from=builder /opt/venv /opt/venv

# Drop privileges so the API never runs as root inside the container.
RUN useradd --create-home appuser
USER appuser

# Copy application code (shared utilities, API app, migrations + entrypoint).
COPY --chown=appuser:appuser backend/shared ./shared
COPY --chown=appuser:appuser backend/api/app ./app
COPY --chown=appuser:appuser backend/api/run.py ./run.py
COPY --chown=appuser:appuser backend/migrations ./migrations

EXPOSE 8000

# HTTP health endpoint is already exposed, so reuse it for the Docker healthcheck.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["python", "run.py"]
