# syntax=docker/dockerfile:1.4

ARG APK_REPO_URL=https://dl-cdn.alpinelinux.org/alpine
ARG GOPROXY_URL=https://proxy.golang.org,direct
# Pinned 2026-02-27 — caddy:2-builder / caddy:2-alpine
ARG CADDY_BUILDER_IMAGE=caddy:2-builder@sha256:9780b126deae015b2c262fa9f4f1f951577e1f6a5fe4d88c0573aeb622071b2d
ARG CADDY_ALPINE_IMAGE=caddy:2-alpine@sha256:3b2a0196e0687279c14c27adff9fc6b44acfa318dbb97eaebe385bdf99e5364c

FROM ${CADDY_BUILDER_IMAGE} AS builder
ARG GOPROXY_URL
ENV GOPROXY=${GOPROXY_URL}

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    xcaddy build \
    --with github.com/caddy-dns/cloudflare@v0.2.2 \
    --output /usr/bin/caddy

FROM ${CADDY_ALPINE_IMAGE}
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

COPY --from=builder --link /usr/bin/caddy /usr/bin/caddy
COPY Caddyfile /etc/caddy/Caddyfile
COPY maintenance.html /srv/maintenance/maintenance.html
# Validate config at build time to fail fast.
RUN caddy validate --config /etc/caddy/Caddyfile && \
    setcap 'cap_net_bind_service=+ep' /usr/bin/caddy && \
    chown -R caddy:caddy /data /config /srv/maintenance

USER caddy
