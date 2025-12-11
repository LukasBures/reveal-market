from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

ERRORS_PATH = Path(__file__).resolve().parents[2] / "contracts" / "cache" / "errors.json"


def load_error_map(path: Path = ERRORS_PATH) -> dict[str, str]:
    """Load selector -> signature map generated from the contracts workspace."""

    try:
        with path.open() as f:
            data: Any = json.load(f)
            if isinstance(data, dict):
                # normalize keys to lowercase for comparisons
                return {k.lower(): str(v) for k, v in data.items()}
    except (FileNotFoundError, PermissionError, OSError):
        return {}
    except JSONDecodeError:
        return {}
    return {}


ERROR_MAP = load_error_map()


def decode_revert(data: str) -> str | None:
    """Return the error signature for a given revert payload (selector only)."""

    if not data or len(data) < 10:
        return None
    selector = data[:10].lower()
    return ERROR_MAP.get(selector)
