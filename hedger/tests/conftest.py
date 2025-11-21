from __future__ import annotations

import importlib
import sys

REQUIRED_MODULES = ["pydantic", "httpx", "tenacity"]
missing = [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]

if missing:
    deps = ", ".join(missing)
    sys.stdout.write(
        f"\nSkipping hedger tests: missing dependencies {deps}. Run 'uv sync --project hedger --extra dev' first.\n"
    )
    raise SystemExit(0)
