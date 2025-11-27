# Caddy deployment notes

- **Image**: Built via `docker/caddy/Dockerfile` with the Cloudflare DNS plugin baked in. The `caddy` service in `docker-compose.yml` builds this image.
- **TLS profiles** (`CADDY_TLS_PROFILE`):
  - `tls_prod` – default HTTP/ALPN ACME.
  - `tls_dns` – DNS-01 with Cloudflare (`CLOUDFLARE_API_TOKEN` required).
  - `tls_local` – internal CA (no public ACME).
- **ACME overrides**: `CADDY_ACME_EMAIL`, `CADDY_ACME_CA`, `CADDY_DNS_RESOLVERS`.
- **Healthcheck**: Caddy exposes the admin API on `localhost:2019` for the container health probe.
- **Config validation**: Run `docker run --rm -v "$(pwd)/docker/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" reveal-market-caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile` before deploying changes.
