# syntax=docker/dockerfile:1.4

ARG BUILDKIT_INLINE_CACHE=1
ARG APK_REPO_URL=https://dl-cdn.alpinelinux.org/alpine

FROM python:3.12-alpine AS base
ARG APK_REPO_URL

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN --mount=type=cache,target=/var/cache/apk set -eux; \
    ALPINE_VERSION="$(cut -d. -f1,2 /etc/alpine-release)"; \
    echo "${APK_REPO_URL}/v${ALPINE_VERSION}/main" > /etc/apk/repositories; \
    echo "${APK_REPO_URL}/v${ALPINE_VERSION}/community" >> /etc/apk/repositories; \
    apk_with_retry() { \
      for i in 1 2 3; do \
        if apk add --no-cache "$@"; then return 0; fi; \
        echo "apk add failed (attempt ${i}), retrying..." >&2; \
        sleep "${i}"; \
      done; \
      return 1; \
    }; \
    apk_with_retry libstdc++

FROM base AS builder
ARG APK_REPO_URL
WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apk set -eux; \
    ALPINE_VERSION="$(cut -d. -f1,2 /etc/alpine-release)"; \
    echo "${APK_REPO_URL}/v${ALPINE_VERSION}/main" > /etc/apk/repositories; \
    echo "${APK_REPO_URL}/v${ALPINE_VERSION}/community" >> /etc/apk/repositories; \
    apk_with_retry() { \
      for i in 1 2 3; do \
        if apk add --no-cache "$@"; then return 0; fi; \
        echo "apk add failed (attempt ${i}), retrying..." >&2; \
        sleep "${i}"; \
      done; \
      return 1; \
    }; \
    apk_with_retry --virtual .build-deps build-base python3-dev libffi-dev openssl-dev

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
