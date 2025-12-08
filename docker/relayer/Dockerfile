FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app/relayer

RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends build-essential gcc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY relayer/pyproject.toml relayer/README.md ./
RUN uv sync --no-dev

COPY relayer/src ./src

ENV PYTHONPATH=/app/relayer/src
ENV HOST=0.0.0.0
ENV PORT=8088

CMD ["uv", "run", "uvicorn", "relayer.main:app", "--host", "0.0.0.0", "--port", "8088"]
