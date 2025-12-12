from __future__ import annotations

import asyncio
import sys

from .config import get_settings
from .storage import HedgerRepository


def main() -> int:
    settings = get_settings()
    repo = HedgerRepository(settings.database_url)
    asyncio.run(repo.check_connection())
    return 0


if __name__ == "__main__":
    sys.exit(main())
