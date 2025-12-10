ARG CADDY_VERSION=2
ARG APK_REPO_URL=https://dl-cdn.alpinelinux.org/alpine
ARG APK_FALLBACK_URL=https://mirror.leaseweb.net/alpine
ARG GOPROXY_URL=direct
FROM caddy:${CADDY_VERSION}-builder AS builder
ARG GOPROXY_URL
ENV GOPROXY=${GOPROXY_URL}

RUN --network=host set -eux; \
    xcaddy_with_retry() { \
      for i in 1 2 3 4 5; do \
        if xcaddy build \
            --with github.com/caddy-dns/cloudflare@v0.2.2 \
            --output /usr/bin/caddy; then \
          return 0; \
        fi; \
        echo "xcaddy build failed (attempt ${i}), retrying..." >&2; \
        sleep "${i}"; \
      done; \
      return 1; \
    }; \
    xcaddy_with_retry

FROM caddy:${CADDY_VERSION}-alpine
ARG APK_REPO_URL
ARG APK_FALLBACK_URL

ARG CADDY_TLS_PROFILE=tls_local
# Default to local TLS so build-time validation succeeds even when no env is provided.
ENV CADDY_TLS_PROFILE=${CADDY_TLS_PROFILE}

RUN --network=host set -eux; \
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
    apk_with_retry curl libcap

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
