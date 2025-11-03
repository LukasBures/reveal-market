"""Reveal Market worker package."""

from __future__ import annotations

import sys
from pathlib import Path

_SHARED_PATH = Path(__file__).resolve().parents[2] / "shared"
if str(_SHARED_PATH) not in sys.path:
    sys.path.append(str(_SHARED_PATH))
