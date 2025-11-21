from __future__ import annotations

import uvicorn
from app.config import get_settings
from app.main import create_app

settings = get_settings()
app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "run:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.environment == "dev",
        log_level=settings.log_level.lower(),
    )
