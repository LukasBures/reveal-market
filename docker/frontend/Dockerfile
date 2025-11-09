FROM node:20-alpine AS deps
# First stage installs dependencies exactly once. node-gyp deps are here so
# optional native modules (utf-8-validate, etc.) compile if pnpm/npm enables them.
RUN apk add --no-cache python3 make g++
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
ARG RM_API_BASE_URL=http://api:8000
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NODE_ENV=production \
    RM_API_BASE_URL=${RM_API_BASE_URL} \
    NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_TELEMETRY_DISABLED=1
# Copy node_modules from deps stage to reuse caches and ensure the exact same
# dependency tree is used during build + runtime extraction.
COPY --from=deps /app/node_modules ./node_modules
COPY frontend ./
# `npm run build` emits the Next standalone server. Remove the build cache so it
# does not inflate the builder layer. Next expects fallback manifest files even
# when empty, so ensure they exist.
RUN npm run build && rm -rf .next/cache && \
    if [ ! -f ".next/fallback-build-manifest.json" ]; then touch ".next/fallback-build-manifest.json"; fi

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

# Copy only the artifacts required by Next's standalone output. The --chown flag
# ensures final ownership belongs to the non-root `node` user we switch to later.

COPY --from=builder --chown=node:node /app/next.config.mjs ./
COPY --from=builder --chown=node:node /app/public ./public
COPY --from=builder --chown=node:node /app/package*.json ./
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/.next/BUILD_ID ./.next/BUILD_ID
COPY --from=builder --chown=node:node /app/.next/app-build-manifest.json ./.next/app-build-manifest.json
COPY --from=builder --chown=node:node /app/.next/prerender-manifest.json ./.next/prerender-manifest.json
COPY --from=builder --chown=node:node /app/.next/routes-manifest.json ./.next/routes-manifest.json
COPY --from=builder --chown=node:node /app/.next/build-manifest.json ./.next/build-manifest.json
COPY --from=builder --chown=node:node /app/.next/fallback-build-manifest.json ./.next/fallback-build-manifest.json
COPY --from=builder --chown=node:node /app/.next/server ./.next/server

# Drop privileges; Next server does not need root access.
USER node

EXPOSE 3000

# Healthcheck hits the API route exposed by Next so we know the server + routing
# layer are running, not just the process.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD wget -qO- http://localhost:3000/api/health || exit 1

CMD ["node", "server.js"]
