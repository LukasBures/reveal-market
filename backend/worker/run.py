from __future__ import annotations

import os

mode = os.getenv("MODE", "prod").lower()
if mode == "dev":
    os.environ.setdefault("LOG_LEVEL", "DEBUG")

from app.main import main  # noqa: E402


if __name__ == "__main__":
    main()
