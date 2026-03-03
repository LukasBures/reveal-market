# syntax=docker/dockerfile:1.4
# docker/frontend/Dockerfile

ARG APK_REPO_URL=https://dl-cdn.alpinelinux.org/alpine
# Pinned 2026-02-27
ARG NODE_IMAGE=node:20-alpine@sha256:09e2b3d9726018aecf269bd35325f46bf75046a643a66d28360ec71132750ec8

# 1) Install dependencies
FROM ${NODE_IMAGE} AS deps
ARG APK_REPO_URL
RUN --mount=type=cache,target=/var/cache/apk set -eux; \
    ALPINE_VERSION="$(cut -d. -f1,2 /etc/alpine-release)"; \
    echo "${APK_REPO_URL}/v${ALPINE_VERSION}/main" > /etc/apk/repositories; \
    echo "${APK_REPO_URL}/v${ALPINE_VERSION}/community" >> /etc/apk/repositories; \
    apk add --no-cache --virtual .build-deps python3 make g++
WORKDIR /app/frontend

COPY frontend/package*.json ./
# Cache npm modules between builds when BuildKit is enabled.
RUN --mount=type=cache,target=/root/.npm npm ci --prefer-offline --no-audit
RUN apk del .build-deps

# 2) Build stage – all NEXT_PUBLIC_* must be passed as build args
FROM ${NODE_IMAGE} AS builder
ARG APK_REPO_URL
RUN --mount=type=cache,target=/var/cache/apk set -eux; \
    ALPINE_VERSION="$(cut -d. -f1,2 /etc/alpine-release)"; \
    echo "${APK_REPO_URL}/v${ALPINE_VERSION}/main" > /etc/apk/repositories; \
    echo "${APK_REPO_URL}/v${ALPINE_VERSION}/community" >> /etc/apk/repositories; \
    apk add --no-cache bash
WORKDIR /app/frontend

COPY --from=deps --link /app/frontend/node_modules ./node_modules
COPY frontend ./

# Build-time envs (these are what Next.js actually embeds)
ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_PRICE_STREAMER_URL
ARG NEXT_PUBLIC_SITE_URL
ARG NEXT_PUBLIC_CHAIN_ID
ARG NEXT_PUBLIC_CHAIN_NAME
ARG NEXT_PUBLIC_RPC_URL
ARG NEXT_PUBLIC_BLOCK_EXPLORER_URL
ARG NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID
ARG NEXT_DISABLE_MINIFY=false
ENV NEXT_TELEMETRY_DISABLED=1

# Export them so Next.js sees them during `npm run build`
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_PRICE_STREAMER_URL=${NEXT_PUBLIC_PRICE_STREAMER_URL}
ENV NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL}
ENV NEXT_PUBLIC_CHAIN_ID=${NEXT_PUBLIC_CHAIN_ID}
ENV NEXT_PUBLIC_CHAIN_NAME=${NEXT_PUBLIC_CHAIN_NAME}
ENV NEXT_PUBLIC_RPC_URL=${NEXT_PUBLIC_RPC_URL}
ENV NEXT_PUBLIC_BLOCK_EXPLORER_URL=${NEXT_PUBLIC_BLOCK_EXPLORER_URL}
ENV NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID=${NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID}
ENV NEXT_DISABLE_MINIFY=${NEXT_DISABLE_MINIFY}

# Optional: if you use this in next.config.mjs
# ENV RUNNING_IN_DOCKER=true

# Reuse npm cache and Next build cache between runs to speed up rebuilds.
RUN --mount=type=cache,target=/root/.npm --mount=type=cache,target=/app/frontend/.next/cache npm run build

# 3) Runtime stage
FROM ${NODE_IMAGE} AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
# Force Next to bind on all interfaces instead of the container hostname.
ENV HOSTNAME=0.0.0.0
ENV LOG_LEVEL=INFO
ENV NEXT_TELEMETRY_DISABLED=1

# Drop privileges to a dedicated runtime user.
ARG APP_USER=nextjs
ARG APP_GROUP=nextjs
RUN id -u "${APP_USER}" >/dev/null 2>&1 || (addgroup -S "${APP_GROUP}" && adduser -S -G "${APP_GROUP}" "${APP_USER}")

# Copy only what the standalone server needs: server bundle, static assets, public assets.
COPY --from=builder --chown=${APP_USER}:${APP_GROUP} /app/frontend/.next/standalone ./
COPY --from=builder --chown=${APP_USER}:${APP_GROUP} /app/frontend/.next/static ./.next/static
COPY --from=builder --chown=${APP_USER}:${APP_GROUP} /app/frontend/public ./public

USER ${APP_USER}

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/healthz').then(r=>{if(!r.ok) process.exit(1)}).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
