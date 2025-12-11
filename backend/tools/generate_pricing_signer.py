#!/usr/bin/env python3
"""
Generate a pricing signer keypair for RM_PRICING_SIGNER_PRIVATE_KEY / PRICING_SIGNER_ADDRESS.

- Writes a timestamped file under backend/tools/ so existing keys are never overwritten.
- Prints the env lines to stdout for convenience.
- WARNING: Do not commit the generated private key.
"""

from __future__ import annotations

import datetime
import pathlib
import secrets
import sys

try:
    from eth_account import Account  # type: ignore
except ImportError as exc:  # pragma: no cover - import guard
    sys.stderr.write(f"eth_account is required to run this script: {exc}\n")
    sys.exit(1)


def main() -> None:
    root = pathlib.Path(__file__).resolve().parent
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
    out_path = root / f"pricing_signer_{ts}.txt"

    # Generate a fresh 32-byte key
    private_bytes = secrets.token_bytes(32)
    acct = Account.from_key(private_bytes)
    priv_hex = "0x" + private_bytes.hex()
    addr = acct.address

    content = (
        "# Pricing signer key (do NOT commit)\n"
        f"# Generated at {datetime.datetime.now(datetime.UTC).isoformat()}Z\n"
        f"RM_PRICING_SIGNER_PRIVATE_KEY={priv_hex}\n"
        f"PRICING_SIGNER_ADDRESS={addr}\n"
    )
    out_path.write_text(content)

    print(f"Wrote pricing signer to {out_path}")
    print("Env lines:")
    print(content)
    print("Remember to keep this file secret and add the private key to your runtime env (not to git).")


if __name__ == "__main__":
    main()
