# syntax=docker/dockerfile:1.4
# docker/frontend/Dockerfile

ARG BUILDKIT_INLINE_CACHE=1

# 1) Install dependencies
FROM node:20-alpine AS deps
RUN --mount=type=cache,target=/var/cache/apk apk add --no-cache --virtual .build-deps python3 make g++
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

# Export them so Next.js sees them during `npm run build`
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_PRICE_STREAMER_URL=${NEXT_PUBLIC_PRICE_STREAMER_URL}
ENV NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL}
ENV NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID=${NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID}
ENV NEXT_PUBLIC_WALLET_CHAINS=${NEXT_PUBLIC_WALLET_CHAINS}

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
