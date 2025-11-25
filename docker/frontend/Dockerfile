FROM node:20-alpine AS deps
RUN apk add --no-cache python3 make g++
WORKDIR /app
COPY frontend/package*.json ./
# Cache npm modules between builds when BuildKit is enabled.
RUN --mount=type=cache,target=/root/.npm npm ci --prefer-offline --no-audit

FROM node:20-alpine AS builder
WORKDIR /app
ARG RM_API_BASE_URL=http://api:8000
ARG RM_OFFLINE_API_BASE_URL=http://api:8000
ARG NEXT_PUBLIC_API_BASE_URL=http://api:8000
ARG NEXT_PUBLIC_PRICE_STREAMER_URL=http://stream:8100
ARG STREAMER_INTERNAL_URL=http://stream:8100
ARG NEXT_PUBLIC_SITE_URL=http://localhost
ARG SITEMAP_API_BASE_URL=http://api:8000
ARG RUNNING_IN_DOCKER=false
ARG LANDING_ACCESS_CODE=
ARG NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID=
ARG NEXT_PUBLIC_WALLET_CHAINS=base
ARG NEXT_BUILD_WORKERS=2
ENV NODE_ENV=production \
    RM_API_BASE_URL=${RM_API_BASE_URL} \
    RM_OFFLINE_API_BASE_URL=${RM_OFFLINE_API_BASE_URL} \
    NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_PUBLIC_PRICE_STREAMER_URL=${NEXT_PUBLIC_PRICE_STREAMER_URL} \
    STREAMER_INTERNAL_URL=${STREAMER_INTERNAL_URL} \
    NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL} \
    SITEMAP_API_BASE_URL=${SITEMAP_API_BASE_URL} \
    RUNNING_IN_DOCKER=${RUNNING_IN_DOCKER} \
    LANDING_ACCESS_CODE=${LANDING_ACCESS_CODE} \
    NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID=${NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID} \
    NEXT_PUBLIC_WALLET_CHAINS=${NEXT_PUBLIC_WALLET_CHAINS} \
    NEXT_TELEMETRY_DISABLED=1 \
    NEXT_BUILD_WORKERS=${NEXT_BUILD_WORKERS}
# Reuse node_modules from deps stage so builds never reinstall packages twice.
COPY --from=deps /app/node_modules ./node_modules
COPY ./frontend ./
# Precompile Tailwind CSS once before Next.js builds so the generated bundle can
# be reused within this stage without lengthy reprocessing.
RUN cp app/globals.css app/globals.source.css \
    && TAILWIND_INPUT=./app/globals.source.css TAILWIND_OUTPUT=./app/globals.css npm run generate:css \
    && npm run build \
    && mv app/globals.source.css app/globals.css

FROM node:20-alpine AS runner
ARG RUNNING_IN_DOCKER=false
ARG LANDING_ACCESS_CODE=
ARG NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID=
ARG NEXT_PUBLIC_WALLET_CHAINS=base
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    RUNNING_IN_DOCKER=${RUNNING_IN_DOCKER} \
    LANDING_ACCESS_CODE=${LANDING_ACCESS_CODE} \
    NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID=${NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID} \
    NEXT_PUBLIC_WALLET_CHAINS=${NEXT_PUBLIC_WALLET_CHAINS}

# Copy only what the standalone server needs: the server bundle itself and the
# compiled assets. No node_modules are required at runtime because the
# standalone output inlines production deps.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public

# Drop privileges; Next server does not need root access.
USER node

EXPOSE 3000

# Healthcheck hits the API route exposed by Next so we know the server + routing
# layer are running, not just the process.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD wget -qO- http://127.0.0.1:3000/api/health || exit 1

CMD ["node", "server.js"]
