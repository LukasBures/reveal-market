ARG CADDY_VERSION=2
FROM caddy:${CADDY_VERSION}-builder AS builder

RUN xcaddy build \
    --with github.com/caddy-dns/cloudflare@v0.2.2 \
    --output /usr/bin/caddy

FROM caddy:${CADDY_VERSION}-alpine

RUN apk add --no-cache curl libcap

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
RUN setcap 'cap_net_bind_service=+ep' /usr/bin/caddy && \
    chown -R caddy:caddy /data /config

USER caddy
