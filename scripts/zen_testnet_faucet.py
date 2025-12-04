#!/usr/bin/env python3
"""
Batch faucet requester for Horizen testnet.

This hits the Caldera hub tRPC endpoint directly instead of driving the browser UI.
Defaults:
- rollup subdomain: horizen-testnet
- recipient address: 0x33c65aac00ace0b48876d9b87990e0c44f780708
- total amount: TARGET_TOTAL_ETH (derived into calls at 0.01 ETH per drip)
- 2s pause between each request
"""

from __future__ import annotations

import logging
import os
import time
from decimal import ROUND_UP, Decimal
from typing import Any

import requests

API_URL = "https://horizen-testnet.hub.caldera.xyz/api/trpc/faucet.requestFaucetFunds"
EXPLORER_BASE = "https://horizen-testnet.explorer.caldera.xyz/tx"

# DEFAULT_ADDRESS = "0x33c65aac00ace0b48876d9b87990e0c44f780708"
# DEFAULT_ADDRESS = "0x0F3d0f9274fA6AAEEbc493EdD44d2979BD75F369" # testnet oracle
# DEFAULT_ADDRESS = "0x65CeDe1252B614ae9fb05e5620EBCbC471DF1627"  # testnet deployer
# DEFAULT_ADDRESS = "0x38C57472479fe7bB4C87e7A4BB23c7AAf10595Fd" # testnet auth signer
DEFAULT_ADDRESS = "0xdAdEbecf077cdA5f86F60a91f76B238F675204f9"  # testnet relayer

DEFAULT_ROLLUP = "horizen-testnet"
DRIP_AMOUNT_ETH = Decimal("0.01")
TURNSTILE_TOKEN =<REDACTED>
TOKEN_ROLLUP_ADDRESS = ""
DELAY_SECONDS = 2.0
# Adjust these to control the run.
TARGET_TOTAL_ETH = Decimal("1.0")
RECIPIENT_ADDRESS = DEFAULT_ADDRESS
ROLLUP_SUBDOMAIN = DEFAULT_ROLLUP


def request_faucet(
    session: requests.Session,
    *,
    rollup_subdomain: str,
    recipient_address: str,
    turnstile_token: str,
    token_rollup_address: str | None,
) -> dict[str, Any]:
    payload = {
        "0": {
            "json": {
                "rollupSubdomain": rollup_subdomain,
                "recipientAddress": recipient_address,
                "turnstileToken": turnstile_token,
                # Empty string is accepted by the backend when no token address is needed.
                "tokenRollupAddress": token_rollup_address or "",
            }
        }
    }
    response = session.post(API_URL, params={"batch": 1}, json=payload, timeout=30)
    response.raise_for_status()

    body = response.json()
    if not isinstance(body, list) or not body:
        raise RuntimeError(f"Unexpected response shape: {body}")

    envelope = body[0]
    result = envelope.get("result", {}).get("data", {}).get("json", {})
    if not result or not result.get("success"):
        error = envelope.get("error") or result
        raise RuntimeError(f"Faucet request failed: {error}")

    return result


def explorer_url(tx_hash: str) -> str:
    return f"{EXPLORER_BASE}/{tx_hash}?tab=index"


def resolve_count() -> int:
    if TARGET_TOTAL_ETH <= 0:
        raise SystemExit("TARGET_TOTAL_ETH must be positive")
    count = int((TARGET_TOTAL_ETH / DRIP_AMOUNT_ETH).to_integral_value(rounding=ROUND_UP))
    return max(1, count)


def effective_total_eth(count: int) -> Decimal:
    return DRIP_AMOUNT_ETH * count


def format_eth(amount: Decimal) -> str:
    return format(amount.normalize(), "f")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("zen_testnet_faucet")

    count = resolve_count()
    total_eth = effective_total_eth(count)

    log.info(
        "Starting faucet loop total=%s ETH (count=%s, delay=%.2fs, address=%s, rollup=%s)",
        format_eth(total_eth),
        count,
        DELAY_SECONDS,
        RECIPIENT_ADDRESS,
        ROLLUP_SUBDOMAIN,
    )
    session = requests.Session()

    for i in range(1, count + 1):
        try:
            result = request_faucet(
                session,
                rollup_subdomain=ROLLUP_SUBDOMAIN,
                recipient_address=RECIPIENT_ADDRESS,
                turnstile_token=TURNSTILE_TOKEN,
                token_rollup_address=TOKEN_ROLLUP_ADDRESS or "",
            )
            tx_hash = result.get("transactionHash") or "<unknown>"
            log.info("[%s/%s] success tx=%s url=%s", i, count, tx_hash, explorer_url(tx_hash))
        except Exception as exc:
            log.error("[%s/%s] failed: %s", i, count, exc)

        if i < count:
            time.sleep(DELAY_SECONDS)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
