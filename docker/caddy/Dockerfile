ARG BUILDKIT_INLINE_CACHE=1
ARG CADDY_VERSION=2
ARG APK_REPO_URL=https://dl-cdn.alpinelinux.org/alpine
ARG GOPROXY_URL=https://proxy.golang.org,direct
ARG CADDY_BUILDER_IMAGE=caddy
ARG CADDY_ALPINE_IMAGE=caddy

# syntax=docker/dockerfile:1.4

FROM ${CADDY_BUILDER_IMAGE}:${CADDY_VERSION}-builder AS builder
ARG GOPROXY_URL
ENV GOPROXY=${GOPROXY_URL}

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    xcaddy build \
    --with github.com/caddy-dns/cloudflare@v0.2.2 \
    --output /usr/bin/caddy

FROM ${CADDY_ALPINE_IMAGE}:${CADDY_VERSION}-alpine
ARG APK_REPO_URL

ARG CADDY_TLS_PROFILE=tls_local
# Default to local TLS so build-time validation succeeds even when no env is provided.
ENV CADDY_TLS_PROFILE=${CADDY_TLS_PROFILE}

RUN --mount=type=cache,target=/var/cache/apk set -eux; \
    ALPINE_VERSION="$(cut -d. -f1,2 /etc/alpine-release)"; \
    echo "${APK_REPO_URL}/v${ALPINE_VERSION}/main" > /etc/apk/repositories; \
    echo "${APK_REPO_URL}/v${ALPINE_VERSION}/community" >> /etc/apk/repositories; \
    apk add --no-cache curl libcap

# Ensure caddy user/group exists (some base images may omit them).
RUN id -u caddy >/dev/null 2>&1 || (addgroup -S caddy && adduser -S -G caddy caddy)
# Guarantee data/config dirs exist before chown.
RUN mkdir -p /data /config

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
COPY Caddyfile /etc/caddy/Caddyfile
# Validate config at build time to fail fast.
RUN caddy validate --config /etc/caddy/Caddyfile && \
    setcap 'cap_net_bind_service=+ep' /usr/bin/caddy && \
    chown -R caddy:caddy /data /config

USER caddy
