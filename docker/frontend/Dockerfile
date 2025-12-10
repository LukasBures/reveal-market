# syntax=docker/dockerfile:1.4
# docker/frontend/Dockerfile

ARG BUILDKIT_INLINE_CACHE=1
ARG APK_REPO_URL=https://dl-cdn.alpinelinux.org/alpine
ARG APK_FALLBACK_URL=https://mirror.leaseweb.net/alpine

# 1) Install dependencies
FROM node:20-alpine AS deps
ARG APK_REPO_URL
ARG APK_FALLBACK_URL
RUN --mount=type=cache,target=/var/cache/apk set -eux; \
    ALPINE_VERSION="$(cut -d. -f1,2 /etc/alpine-release)"; \
    echo "${APK_REPO_URL}/v${ALPINE_VERSION}/main" > /etc/apk/repositories; \
    echo "${APK_REPO_URL}/v${ALPINE_VERSION}/community" >> /etc/apk/repositories; \
    if [ -n "${APK_FALLBACK_URL}" ]; then \
      echo "${APK_FALLBACK_URL}/v${ALPINE_VERSION}/main" >> /etc/apk/repositories; \
      echo "${APK_FALLBACK_URL}/v${ALPINE_VERSION}/community" >> /etc/apk/repositories; \
    fi; \
    apk_with_retry() { \
      for i in 1 2 3 4 5; do \
        if apk add --no-cache "$@"; then return 0; fi; \
        echo "apk add failed (attempt ${i}), retrying..." >&2; \
        sleep "${i}"; \
      done; \
      return 1; \
    }; \
    apk_with_retry --virtual .build-deps python3 make g++
WORKDIR /app/frontend

COPY frontend/package*.json ./
# Cache npm modules between builds when BuildKit is enabled.
RUN --mount=type=cache,target=/root/.npm npm ci --prefer-offline --no-audit
RUN apk del .build-deps

# 2) Build stage – all NEXT_PUBLIC_* must be passed as build args
FROM node:20-alpine AS builder
WORKDIR /app/frontend

COPY --from=deps /app/frontend/node_modules ./node_modules
COPY frontend ./

# Build-time envs (these are what Next.js actually embeds)
ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_PRICE_STREAMER_URL
ARG NEXT_PUBLIC_SITE_URL
ARG NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID
ARG NEXT_PUBLIC_WALLET_CHAINS
ARG NEXT_DISABLE_MINIFY=false
ENV NEXT_TELEMETRY_DISABLED=1

# Export them so Next.js sees them during `npm run build`
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_PRICE_STREAMER_URL=${NEXT_PUBLIC_PRICE_STREAMER_URL}
ENV NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL}
ENV NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID=${NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID}
ENV NEXT_PUBLIC_WALLET_CHAINS=${NEXT_PUBLIC_WALLET_CHAINS}
ENV NEXT_DISABLE_MINIFY=${NEXT_DISABLE_MINIFY}

# Optional: if you use this in next.config.mjs
# ENV RUNNING_IN_DOCKER=true

RUN npm run build

# 3) Runtime stage
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
# Force Next to bind on all interfaces instead of the container hostname.
ENV HOSTNAME=0.0.0.0
ENV LOG_LEVEL=INFO
ENV NEXT_TELEMETRY_DISABLED=1

# Copy only what the standalone server needs: server bundle, static assets, public assets.
COPY --from=builder /app/frontend/.next/standalone ./
COPY --from=builder /app/frontend/.next/static ./.next/static
COPY --from=builder /app/frontend/public ./public

# Drop privileges to a dedicated runtime user.
ARG APP_USER=nextjs
ARG APP_GROUP=nextjs
RUN id -u "${APP_USER}" >/dev/null 2>&1 || (addgroup -S "${APP_GROUP}" && adduser -S -G "${APP_GROUP}" "${APP_USER}")
RUN chown -R "${APP_USER}:${APP_GROUP}" /app
USER ${APP_USER}

EXPOSE 3000

CMD ["node", "server.js"]
