from __future__ import annotations

import uvicorn
from app.config import get_settings
from app.main import create_app

settings = get_settings()
if settings.log_level:
    # Ensure uvicorn and app share the same resolved level (default INFO).
    resolved = settings.log_level.upper()
    settings.log_level = resolved

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "run:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.environment == "dev",
        log_level=settings.log_level.lower(),
    )
