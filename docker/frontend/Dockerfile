FROM node:20-alpine AS deps
RUN apk add --no-cache python3 make g++
WORKDIR /app
COPY frontend/package*.json ./
# Cache npm modules between builds when BuildKit is enabled.
RUN --mount=type=cache,target=/root/.npm npm ci

FROM node:20-alpine AS builder
WORKDIR /app
ARG RM_API_BASE_URL=http://api:8000
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG RUNNING_IN_DOCKER=false
ARG LANDING_ACCESS_CODE=
ENV NODE_ENV=production \
    RM_API_BASE_URL=${RM_API_BASE_URL} \
    NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    RUNNING_IN_DOCKER=${RUNNING_IN_DOCKER} \
    LANDING_ACCESS_CODE=${LANDING_ACCESS_CODE} \
    NEXT_TELEMETRY_DISABLED=1
# Reuse node_modules from deps stage so builds never reinstall packages twice.
COPY --from=deps /app/node_modules ./node_modules
COPY ./frontend ./
# `next build` emits the standalone server; prune heavy cache artifacts to keep
# the builder layer slim.
RUN npm run build && rm -rf .next/cache

FROM node:20-alpine AS runner
ARG RUNNING_IN_DOCKER=false
ARG LANDING_ACCESS_CODE=
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    RUNNING_IN_DOCKER=${RUNNING_IN_DOCKER} \
    LANDING_ACCESS_CODE=${LANDING_ACCESS_CODE}

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
