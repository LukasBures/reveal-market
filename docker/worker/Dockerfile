FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3

WORKDIR /worker

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "poetry==${POETRY_VERSION}"

COPY backend/worker/pyproject.toml ./pyproject.toml
COPY backend/shared ./shared

RUN poetry export --only main --format requirements.txt --output /tmp/requirements.txt --without-hashes

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/worker \
    MODE=prod

WORKDIR /worker

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /tmp/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

RUN useradd --create-home workeruser
USER workeruser

COPY --chown=workeruser:workeruser backend/shared ./shared
COPY --chown=workeruser:workeruser backend/worker/app ./app
COPY --chown=workeruser:workeruser backend/worker/run.py ./run.py

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -m app.healthcheck

CMD ["python", "run.py"]
