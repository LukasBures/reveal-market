#!/usr/bin/env python3
"""
Generate a mapping of custom error selectors to names for frontend/backend decoders.

Usage:
  python scripts/generate_error_selectors.py > contracts/cache/errors.json
  # optional: copy to frontend
  python scripts/generate_error_selectors.py --write-frontend

This avoids depending on `forge inspect` during CI; selectors are derived by hashing
the canonical error signatures found in contracts/zen/src.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from eth_utils import keccak

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT / "contracts" / "zen" / "src"
FRONTEND_ERRORS = ROOT / "frontend" / "lib" / "errors.json"


def parse_errors_from_file(path: Path) -> list[str]:
    source = path.read_text()
    return re.findall(r"error\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)", source)


def canonical_sig(name: str, params: str) -> str:
    params = params.strip()
    return f"{name}({params})" if params else f"{name}()"


def selector(sig: str) -> str:
    return "0x" + keccak(text=sig).hex()[:8]


def main() -> None:
    write_frontend = "--write-frontend" in sys.argv
    errors: dict[str, str] = {}
    for solidity in CONTRACTS_DIR.glob("**/*.sol"):
        for name, params in parse_errors_from_file(solidity):
            sig = canonical_sig(name, params)
            errors[sig] = selector(sig)
    # Reverse map selector -> signature for easier decoding
    selector_map = {v: k for k, v in sorted(errors.items(), key=lambda item: item[0])}
    output = json.dumps(selector_map, indent=2)
    if write_frontend:
        FRONTEND_ERRORS.write_text(output)
        print(f"Updated {FRONTEND_ERRORS.relative_to(ROOT)}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
