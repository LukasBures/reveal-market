from __future__ import annotations

import os

import uvicorn


def main() -> None:
    mode = os.getenv("MODE", "prod").lower()
    if mode == "dev":
        os.environ.setdefault("LOG_LEVEL", "DEBUG")

    host_default = "127.0.0.1" if mode == "dev" else "0.0.0.0"
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
        )
    else:
        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            log_config=None,
            workers=workers,
        )


if __name__ == "__main__":
    main()
