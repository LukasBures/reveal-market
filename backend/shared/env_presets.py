from __future__ import annotations

import os
from typing import Any


def resolve_mode() -> str:
    env = (os.getenv("RM_ENVIRONMENT") or "").lower()
    if env in PRESETS:
        return env
    if env in {"prod", "production"}:
        return "prod"
    if env in {"dev", "development", "local", "test", "testing"}:
        return "local"
    return "local"


PRESETS: dict[str, dict[str, Any]] = {
    "local": {
        # --- API ---
        "api_host": "0.0.0.0",  # noqa: S104 - containers must bind on all interfaces
        "api_allowed_hosts": [
            "localhost",
            "localhost:8000",
            "127.0.0.1",
            "127.0.0.1:8000",
            "api",
            "api:8000",
            "revealmarket.xyz",
            "api.revealmarket.xyz",
            "stream.revealmarket.xyz",
            "testserver",
        ],
        "api_cors_origins": [
            "http://localhost",
            "http://localhost:3000",
            "http://127.0.0.1",
            "http://127.0.0.1:3000",
            "http://localhost:8100",
            "http://streamer:8100",
            "http://api.localhost",
            "http://stream.localhost",
        ],
        "api_internal_base_url": "http://api:8000",
        "api_public_base_url": "http://localhost:8000",
        "healthcheck_host": "localhost",
        "rate_limit_enabled": False,
        "rate_limit_trusted_proxies": ["127.0.0.1"],
        "run_migrations_on_startup": True,
        "market_commit_lead_seconds": 360,
        # --- Streamer ---
        "streamer_public": "http://localhost:8100",
        "streamer_internal": "http://streamer:8100",
        "streamer_cors_origins": [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "https://streamer.localhost",
        ],
        # --- Worker ---
        "worker_memory_log_enabled": True,
        "worker_memory_log_every_n_pages": 10,
        "worker_memory_trim_threshold_mb": 1400,
        "worker_memory_abort_threshold_mb": 1700,
        "polymarket_stream_persist": True,
        "default_commit_lead_seconds": 360,
        # --- Hedger ---
        "hedger_environment": "dev",
        # --- Caddy ---
        "caddy_tls_profile": "tls_local",
        # --- Frontend (reference values for docker-compose / generate_env.sh) ---
        "frontend_api_base_url": "http://localhost:8000",
        "frontend_streamer_url": "http://localhost:8100",
        "frontend_site_url": "http://localhost:3000",
        # --- Monitoring ---
        "grafana_anonymous_enabled": True,
        "grafana_root_url": "http://localhost:3001",
        # --- Prover ---
        "prover_version": "dev",
    },
    "prod": {
        # --- API ---
        "api_host": "0.0.0.0",  # noqa: S104 - containers must bind on all interfaces
        "api_allowed_hosts": [
            "revealmarket.xyz",
            "api.revealmarket.xyz",
            "stream.revealmarket.xyz",
            "api",
            "api:8000",
            "localhost",
            "127.0.0.1",
        ],
        "api_cors_origins": [
            "https://revealmarket.xyz",
            "https://api.revealmarket.xyz",
            "https://stream.revealmarket.xyz",
        ],
        "api_internal_base_url": "http://api:8000",
        "api_public_base_url": "https://api.revealmarket.xyz",
        "healthcheck_host": "api.revealmarket.xyz",
        "rate_limit_enabled": True,
        "rate_limit_trusted_proxies": ["172.16.0.0/12", "127.0.0.1"],
        "run_migrations_on_startup": False,
        "market_commit_lead_seconds": 86400,
        # --- Streamer ---
        "streamer_public": "https://stream.revealmarket.xyz",
        "streamer_internal": "http://streamer:8100",
        "streamer_cors_origins": [
            "https://revealmarket.xyz",
            "https://stream.revealmarket.xyz",
        ],
        # --- Worker ---
        "worker_memory_log_enabled": False,
        "worker_memory_log_every_n_pages": 25,
        "worker_memory_trim_threshold_mb": 0,
        "worker_memory_abort_threshold_mb": 0,
        "polymarket_stream_persist": False,
        "default_commit_lead_seconds": 86400,
        # --- Hedger ---
        "hedger_environment": "production",
        # --- Caddy ---
        "caddy_tls_profile": "tls_prod",
        # --- Frontend (reference values for docker-compose / generate_env.sh) ---
        "frontend_api_base_url": "https://api.revealmarket.xyz",
        "frontend_streamer_url": "https://stream.revealmarket.xyz",
        "frontend_site_url": "https://revealmarket.xyz",
        # --- Monitoring ---
        "grafana_anonymous_enabled": False,
        "grafana_root_url": "https://grafana.revealmarket.xyz",
        # --- Prover ---
        "prover_version": "prod",
    },
}


def get_preset() -> dict[str, Any]:
    return PRESETS.get(resolve_mode(), PRESETS["local"])
