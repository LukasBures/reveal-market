# Caddy deployment notes

- **Image**: Built via `docker/caddy/Dockerfile` with the Cloudflare DNS plugin baked in. The `caddy` service in `docker-compose.yml` builds this image.
- **Runtime**: Builder/runtime Caddy versions are pinned via `CADDY_VERSION`; the binary is `setcap`-enabled so it can bind 80/443 while running as the `caddy` user.
- **TLS profiles** (`CADDY_TLS_PROFILE`):
  - `tls_prod` – default HTTP/ALPN ACME.
  - `tls_dns` – DNS-01 with Cloudflare (`CLOUDFLARE_API_TOKEN` required).
  - `tls_local` – internal CA (no public ACME).
- **ACME overrides**: `CADDY_ACME_EMAIL`, `CADDY_ACME_CA`, `CADDY_DNS_RESOLVERS`.
- **Healthcheck**: Caddy exposes the admin API on `localhost:2019` for the container health probe.
- **Config validation**: Run `docker run --rm -v "$(pwd)/docker/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" reveal-market-caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile` before deploying changes. The built image includes the Cloudflare DNS module required by the Caddyfile.
- **Client IPs**: The Caddyfile trusts Cloudflare’s IPv4/IPv6 ranges and `CF-Connecting-IP`/`X-Forwarded-For`/`X-Real-IP` so rate limiting and logs see real client addresses behind the proxy. Validate with the built image (includes the Cloudflare DNS module), not stock `caddy:2`.
- **Upstream health**: Reverse proxies now probe `/healthz` with quick failover (`max_fails=2`, `fail_duration=30s`) so unhealthy backends are shed quickly.
- **Access logs**: API and streamer vhosts emit JSON access logs; frontend remains quiet to limit noise. Tune sampling or exclusions if volume grows.
