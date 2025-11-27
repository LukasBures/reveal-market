FROM caddy:2.8.4-builder AS builder

RUN xcaddy build \
    --with github.com/caddy-dns/cloudflare \
    --with github.com/caddyserver/caddy/v2@v2.8.4 \
    --output /usr/bin/caddy

FROM caddy:2.8.4-alpine

RUN apk add --no-cache curl

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
