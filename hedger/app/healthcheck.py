from __future__ import annotations

import sys

from .config import get_settings
from .storage import HedgerRepository


def main() -> int:
    settings = get_settings()
    repo = HedgerRepository(settings.database_url)
    repo.check_connection()
    return 0


if __name__ == "__main__":
    sys.exit(main())
