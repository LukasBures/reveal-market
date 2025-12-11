from __future__ import annotations

import os

import uvicorn
from app.logging_config import resolve_log_level


def main() -> None:
    mode = os.getenv("MODE", "prod").lower()
    log_level_default = "DEBUG" if mode == "dev" else "INFO"
    log_level_name, _ = resolve_log_level(log_level_default)
    os.environ["LOG_LEVEL"] = log_level_name

    # Bind to 0.0.0.0 in containers so health checks can reach the API; safe because
    # Docker publishes explicit ports.
    if mode == "dev":
        host_default = "127.0.0.1"
    else:
        host_default = "0.0.0.0"  # noqa: S104
    host = os.getenv("HOST") or host_default
    port = int(os.getenv("PORT", "8000"))
    workers = int(os.getenv("APP_WORKERS", "2"))

    if mode == "dev":
        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            reload=True,
            reload_dirs=["app", "shared"],
            log_config=None,
            log_level=log_level_name.lower(),
            loop="uvloop",
            http="httptools",
        )
    else:
        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            log_config=None,
            log_level=log_level_name.lower(),
            workers=workers,
            loop="uvloop",
            http="httptools",
        )


if __name__ == "__main__":
    main()
