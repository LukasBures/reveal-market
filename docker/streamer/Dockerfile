# syntax=docker/dockerfile:1.4

ARG BUILDKIT_INLINE_CACHE=1

FROM python:3.12-alpine AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN --mount=type=cache,target=/var/cache/apk apk add --no-cache libstdc++

FROM base AS builder
WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apk apk add --no-cache --virtual .build-deps build-base python3-dev libffi-dev openssl-dev

COPY streamer/pyproject.toml /app/pyproject.toml
COPY streamer/README.md /app/README.md
COPY streamer/app /app/app

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix /install hatchling "uvicorn[standard]" .
RUN apk del .build-deps

FROM base
WORKDIR /app

COPY --from=builder /install /usr/local
COPY streamer/app /app/app
COPY backend/shared /app/shared

EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
