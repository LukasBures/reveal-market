#!/usr/bin/env python3
"""
Send native ETH from a generated key to a destination address.

Defaults:
- sender/private key: scripts/generated/testnet_zenith_token_random_1764886505.txt
- RPC URL: Horizen testnet public RPC (override with --rpc-url)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from web3 import HTTPProvider, Web3
from web3.exceptions import Web3Exception

try:
    from web3.middleware import geth_poa_middleware as _poa_middleware  # type: ignore[attr-defined]
except ImportError:
    _poa_middleware = None

try:
    from web3.middleware import ExtraDataToPOAMiddleware  # type: ignore[attr-defined]
except ImportError:
    ExtraDataToPOAMiddleware = None  # type: ignore[assignment]

DEFAULT_RPC_URL = os.getenv("NEXT_PUBLIC_RPC_URL", "https://mainnet.base.org")
DEFAULT_EXPLORER_URL = os.getenv("NEXT_PUBLIC_BLOCK_EXPLORER_URL", "https://basescan.org")
DEFAULT_KEYFILE = Path(__file__).resolve().parent / "generated" / "testnet_zenith_token_random_1764886505.txt"
DEFAULT_AMOUNT = ""  # noqa: S105
# Optional default destination; leave blank to require --to.
DEFAULT_DESTINATION = ""  # noqa: S105


def load_sender_credentials(path: Path) -> tuple[str, str]:
    tokens = {}
    for chunk in path.read_text(encoding="utf-8").strip().split():
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        tokens[key.strip()] = value.strip()

    try:
        address = tokens["address"]
        private_key = tokens["private_key"]
    except KeyError as exc:  # pragma: no cover - CLI helper
        raise ValueError(f"Missing address/private_key in {path}") from exc

    return address, private_key


def to_wei_amount(amount: str) -> int:
    try:
        value = Decimal(amount)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount: {amount}") from exc

    if value <= 0:
        raise ValueError("Amount must be positive")

    wei_value = value * Decimal(10**18)
    if wei_value != wei_value.to_integral_value():
        raise ValueError(f"Amount {amount} would lose precision in wei")
    return int(wei_value)


def build_web3(rpc_url: str) -> Web3:
    web3 = Web3(HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
    if _poa_middleware is not None:
        web3.middleware_onion.inject(_poa_middleware, layer=0)
    elif ExtraDataToPOAMiddleware is not None:
        web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if not web3.is_connected():  # pragma: no cover - connectivity guard
        raise ConnectionError(f"Failed to connect to RPC at {rpc_url}")
    return web3


def main() -> int:
    parser = argparse.ArgumentParser(description="Send native ETH using a stored private key.")
    parser.add_argument("--rpc-url", default=DEFAULT_RPC_URL, help="EVM RPC endpoint.")
    parser.add_argument("--explorer-base", default=DEFAULT_EXPLORER_URL, help="Block explorer base URL for logging.")
    parser.add_argument(
        "--to",
        dest="destination",
        default=DEFAULT_DESTINATION,
        help="Recipient address (defaults to DEFAULT_DESTINATION at top of file).",
    )
    parser.add_argument(
        "--amount",
        default=DEFAULT_AMOUNT,
        help="Human-readable ETH amount (defaults to DEFAULT_AMOUNT at top of file).",
    )
    parser.add_argument(
        "--keyfile",
        default=str(DEFAULT_KEYFILE),
        help="Path to file containing address=<addr> private_key=<hex>.",
    )
    parser.add_argument(
        "--gas-price-gwei",
        type=float,
        default=None,
        help="Optional gas price override (gwei). Uses node suggestion when omitted.",
    )
    parser.add_argument("--skip-balance-check", action="store_true", help="Send even if local balance check fails.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("send_eth")

    if not args.destination:
        log.error("Destination address is missing. Set DEFAULT_DESTINATION or pass --to.")
        return 1
    if not args.amount:
        log.error("Amount is missing. Set DEFAULT_AMOUNT or pass --amount.")
        return 1

    try:
        sender_addr_raw, private_key = load_sender_credentials(Path(args.keyfile))
    except (OSError, ValueError) as exc:
        log.error("Failed to load keyfile: %s", exc)
        return 1

    try:
        web3 = build_web3(args.rpc_url)
    except ConnectionError as exc:
        log.error("%s", exc)
        return 1

    sender_address = web3.to_checksum_address(sender_addr_raw)
    destination = web3.to_checksum_address(args.destination)
    account = web3.eth.account.from_key(private_key)
    if account.address != sender_address:
        log.warning("Keyfile address (%s) does not match derived address (%s)", sender_address, account.address)
        sender_address = account.address
    log.info("Using chain_id=%s sender=%s", web3.eth.chain_id, sender_address)

    try:
        amount_wei = to_wei_amount(args.amount)
    except ValueError as exc:
        log.error("%s", exc)
        return 1

    try:
        balance = web3.eth.get_balance(sender_address)
        log.info("Sender balance: %s wei", balance)
        if not args.skip_balance_check and amount_wei > int(balance):
            log.error(
                "Insufficient balance: requested %s ETH (%s wei), available %s wei", args.amount, amount_wei, balance
            )
            return 1
    except Web3Exception as exc:
        if args.skip_balance_check:
            log.warning("Balance check failed but continuing due to --skip-balance-check: %s", exc)
        else:
            log.error("Balance check failed; rerun with --skip-balance-check to ignore: %s", exc)
            return 1

    nonce = web3.eth.get_transaction_count(sender_address, "pending")
    log.info("Using nonce=%s", nonce)
    if args.gas_price_gwei is not None:
        gas_price = web3.to_wei(Decimal(str(args.gas_price_gwei)), "gwei")
    else:
        gas_price = web3.eth.gas_price
    log.info("Using gas_price=%s wei", gas_price)

    tx = {
        "from": sender_address,
        "to": destination,
        "value": amount_wei,
        "nonce": nonce,
        "gasPrice": gas_price,
        "chainId": web3.eth.chain_id,
    }

    try:
        estimated_gas = web3.eth.estimate_gas(tx)
    except Web3Exception as exc:
        log.error("Gas estimation failed: %s", exc)
        return 1

    tx["gas"] = int(estimated_gas * 1.2)
    log.info("Estimated gas=%s final_gas=%s", estimated_gas, tx["gas"])

    signed_tx = account.sign_transaction(tx)
    raw_tx = getattr(signed_tx, "raw_transaction", None)
    if raw_tx is None:
        raw_tx = getattr(signed_tx, "rawTransaction", None)
    if raw_tx is None:  # pragma: no cover - defensive for unexpected web3 variants
        log.error("Signed transaction is missing raw transaction bytes")
        return 1

    try:
        tx_hash = web3.eth.send_raw_transaction(raw_tx)
    except Web3Exception as exc:
        log.error("Failed to send transaction: %s", exc)
        return 1

    tx_hash_hex = tx_hash.hex()
    log.info(
        "Sent transfer tx=%s amount=%s ETH (%s wei) from=%s to=%s",
        tx_hash_hex,
        args.amount,
        amount_wei,
        sender_address,
        destination,
    )
    explorer_url = f"{args.explorer_base.rstrip('/')}/tx/0x{tx_hash_hex}"
    log.info("Explorer URL: %s", explorer_url)

    try:
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
        log.info(
            "Tx mined status=%s block=%s gasUsed=%s",
            receipt.get("status"),
            receipt.get("blockNumber"),
            receipt.get("gasUsed"),
        )
    except Web3Exception as exc:
        log.warning("Transaction sent but receipt wait failed: %s", exc)

    return 0


if __name__ == "__main__":
    sys.exit(main())
