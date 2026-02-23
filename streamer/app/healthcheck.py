from __future__ import annotations

import sys
import urllib.request


def main() -> int:
    try:
        with urllib.request.urlopen("http://localhost:8100/healthz", timeout=5) as resp:  # nosec B310
            if resp.status != 200:
                print(f"[healthcheck] unexpected status: {resp.status}", file=sys.stderr)
                return 1
    except Exception as exc:  # pragma: no cover - healthcheck path
        print(f"[healthcheck] failed to reach /healthz: {exc}", file=sys.stderr)
        return 1
    print("[healthcheck] ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
