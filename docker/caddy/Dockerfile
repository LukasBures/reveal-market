FROM caddy:2-builder AS builder

RUN xcaddy build \
    --with github.com/caddy-dns/cloudflare@v0.2.2 \
    --output /usr/bin/caddy

FROM caddy:2-alpine

RUN apk add --no-cache curl

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
