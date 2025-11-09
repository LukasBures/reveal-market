FROM node:20-alpine AS deps
# node-gyp requirements (utf-8-validate, etc.)
RUN apk add --no-cache python3 make g++
WORKDIR /app
COPY frontend/package*.json ./
RUN npm install

FROM node:20-alpine AS builder
WORKDIR /app
ARG RM_API_BASE_URL=http://api:8000
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NODE_ENV=production \
    RM_API_BASE_URL=${RM_API_BASE_URL} \
    NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
# Copy node_modules from deps stage to reuse caches
COPY --from=deps /app/node_modules ./node_modules
COPY frontend ./
RUN npm run build && rm -rf .next/cache && \
    if [ ! -f ".next/fallback-build-manifest.json" ]; then touch ".next/fallback-build-manifest.json"; fi

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

COPY --from=builder /app/next.config.mjs ./
COPY --from=builder /app/public ./public
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/.next/BUILD_ID ./.next/BUILD_ID
COPY --from=builder /app/.next/app-build-manifest.json ./.next/app-build-manifest.json
COPY --from=builder /app/.next/prerender-manifest.json ./.next/prerender-manifest.json
COPY --from=builder /app/.next/routes-manifest.json ./.next/routes-manifest.json
COPY --from=builder /app/.next/build-manifest.json ./.next/build-manifest.json
COPY --from=builder /app/.next/fallback-build-manifest.json ./.next/fallback-build-manifest.json
COPY --from=builder /app/.next/server ./.next/server

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD wget -qO- http://localhost:3000/api/health || exit 1

CMD ["node", "server.js"]
