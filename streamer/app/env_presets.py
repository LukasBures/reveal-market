from __future__ import annotations

import os


def resolve_mode() -> str:
    mode = (os.getenv("MODE") or os.getenv("STREAMER_ENVIRONMENT") or "").lower()
    if mode in {"prod", "production"}:
        return "prod"
    return "local"


PRESETS: dict[str, dict[str, object]] = {
    "local": {
        "api_cors_origins": [
            "http://localhost",
            "http://localhost:3000",
            "http://127.0.0.1",
            "http://127.0.0.1:3000",
            "http://localhost:8100",
            "http://api.localhost",
            "http://stream.localhost",
        ],
        "streamer_public": "http://localhost:8100",
        "streamer_internal": "http://streamer:8100",
    },
    "prod": {
        "api_cors_origins": [
            "https://revealmarket.xyz",
            "https://api.revealmarket.xyz",
            "https://stream.revealmarket.xyz",
        ],
        "streamer_public": "https://stream.revealmarket.xyz",
        "streamer_internal": "https://stream.revealmarket.xyz",
    },
}


def get_preset() -> dict[str, object]:
    return PRESETS.get(resolve_mode(), PRESETS["local"])
