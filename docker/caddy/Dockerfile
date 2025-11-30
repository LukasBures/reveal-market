ARG CADDY_VERSION=2
FROM caddy:${CADDY_VERSION}-builder AS builder

RUN xcaddy build \
    --with github.com/caddy-dns/cloudflare@v0.2.2 \
    --output /usr/bin/caddy

FROM caddy:${CADDY_VERSION}-alpine

ARG CADDY_TLS_PROFILE=tls_local
# Default to local TLS so build-time validation succeeds even when no env is provided.
ENV CADDY_TLS_PROFILE=${CADDY_TLS_PROFILE}

RUN apk add --no-cache curl libcap

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
