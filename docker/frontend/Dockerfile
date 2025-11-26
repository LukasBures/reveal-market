# docker/frontend/Dockerfile

# 1) Install dependencies
FROM node:20-alpine AS deps
RUN apk add --no-cache python3 make g++
WORKDIR /app

COPY frontend/package*.json ./
# Cache npm modules between builds when BuildKit is enabled.
RUN --mount=type=cache,target=/root/.npm npm ci --prefer-offline --no-audit

# 2) Build stage – all NEXT_PUBLIC_* must be passed as build args
FROM node:20-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY frontend ./frontend

WORKDIR /app/frontend

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
WORKDIR /app/frontend

ENV NODE_ENV=production
ENV PORT=3000

# Copy built app
COPY --from=builder /app/frontend ./

EXPOSE 3000

CMD ["npm", "start"]