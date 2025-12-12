from __future__ import annotations

import os

from app.logging_config import resolve_log_level

env = (os.getenv("RM_ENVIRONMENT") or "prod").lower()
dev_like = env in {"dev", "development", "local"}
log_level_default = "DEBUG" if dev_like else "INFO"
log_level_name, _ = resolve_log_level(log_level_default)
os.environ["LOG_LEVEL"] = log_level_name

from app.main import main  # noqa: E402

if __name__ == "__main__":
    main()
