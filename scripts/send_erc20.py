#!/usr/bin/env python3
"""
Send ERC-20 tokens from a generated key to a destination address.

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
from typing import Any

from web3 import HTTPProvider, Web3
from web3.contract.contract import Contract
from web3.exceptions import Web3Exception

try:
    from web3.middleware import geth_poa_middleware as _poa_middleware  # type: ignore[attr-defined]
except ImportError:
    _poa_middleware = None

try:
    from web3.middleware import ExtraDataToPOAMiddleware  # type: ignore[attr-defined]
except ImportError:
    ExtraDataToPOAMiddleware = None  # type: ignore[assignment]

DEFAULT_RPC_URL = os.getenv("RM_RPC_URL", os.getenv("NEXT_PUBLIC_RPC_URL", "https://horizen.calderachain.xyz/http"))
DEFAULT_EXPLORER_URL = os.getenv("NEXT_PUBLIC_BLOCK_EXPLORER_URL", "https://horizen.calderaexplorer.xyz")
DEFAULT_KEYFILE = Path(__file__).resolve().parent / "generated" / "mainnet_funding_wallet.txt"
# Edit these to set a default token and amount.
DEFAULT_TOKEN_ADDRESS = os.getenv("ZEN_TOKEN_ADDRESS", "0x57da2D504bf8b83Ef304759d9f2648522D7a9280")  # noqa: S105
DEFAULT_TOKEN_AMOUNT = "2"  # noqa: S105
# Optional default destination; leave blank to require --to.
DEFAULT_DESTINATION = "0x9D9E384Fb4425B90A1537Dd106CeB3fc79887f56"  # noqa: S105

ERC20_ABI: list[dict[str, Any]] = [
    {
        "constant": False,
        "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


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


def to_base_units(amount: str, decimals: int) -> int:
    try:
        value = Decimal(amount)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount: {amount}") from exc

    if value <= 0:
        raise ValueError("Amount must be positive")

    scale = Decimal(10) ** decimals
    scaled = value * scale
    if scaled != scaled.to_integral_value():
        raise ValueError(f"Amount {amount} would lose precision with {decimals} decimals")
    return int(scaled)


def build_web3(rpc_url: str) -> Web3:
    web3 = Web3(HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
    if _poa_middleware is not None:
        web3.middleware_onion.inject(_poa_middleware, layer=0)
    elif ExtraDataToPOAMiddleware is not None:
        web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if not web3.is_connected():  # pragma: no cover - connectivity guard
        raise ConnectionError(f"Failed to connect to RPC at {rpc_url}")
    return web3


def prepare_contract(web3: Web3, token_address: str) -> Contract:
    checksum_address = web3.to_checksum_address(token_address)
    return web3.eth.contract(address=checksum_address, abi=ERC20_ABI)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send ERC-20 tokens using a stored private key.")
    parser.add_argument("--rpc-url", default=DEFAULT_RPC_URL, help="EVM RPC endpoint.")
    parser.add_argument("--explorer-base", default=DEFAULT_EXPLORER_URL, help="Block explorer base URL for logging.")
    parser.add_argument(
        "--token",
        default=DEFAULT_TOKEN_ADDRESS,
        help="ERC-20 token address (defaults to DEFAULT_TOKEN_ADDRESS at top of file).",
    )
    parser.add_argument(
        "--to",
        dest="destination",
        default=DEFAULT_DESTINATION,
        help="Recipient address (defaults to DEFAULT_DESTINATION at top of file).",
    )
    parser.add_argument(
        "--amount",
        default=DEFAULT_TOKEN_AMOUNT,
        help="Human-readable token amount (defaults to DEFAULT_TOKEN_AMOUNT at top of file).",
    )
    parser.add_argument(
        "--keyfile",
        default=str(DEFAULT_KEYFILE),
        help="Path to file containing address=<addr> private_key=<hex> (default: zenith token key).",
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
    log = logging.getLogger("send_erc20")

    if not args.token:
        log.error("Token address is missing. Set DEFAULT_TOKEN_ADDRESS or pass --token.")
        return 1
    if not args.amount:
        log.error("Amount is missing. Set DEFAULT_TOKEN_AMOUNT or pass --amount.")
        return 1
    if not args.destination:
        log.error("Destination address is missing. Set DEFAULT_DESTINATION or pass --to.")
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

    contract = prepare_contract(web3, args.token)
    try:
        decimals = contract.functions.decimals().call()
        symbol = contract.functions.symbol().call()
    except Web3Exception as exc:
        log.error("Failed to read token metadata: %s", exc)
        return 1

    try:
        amount_int = to_base_units(args.amount, int(decimals))
    except ValueError as exc:
        log.error("%s", exc)
        return 1

    if not args.skip_balance_check:
        try:
            balance = contract.functions.balanceOf(sender_address).call()
            if amount_int > int(balance):
                log.error(
                    "Insufficient token balance: requested %s %s (%s base units), available %s",
                    args.amount,
                    symbol,
                    amount_int,
                    balance,
                )
                return 1
        except Web3Exception as exc:
            log.error("Balance check failed; rerun with --skip-balance-check to ignore: %s", exc)
            return 1

    nonce = web3.eth.get_transaction_count(sender_address, "pending")
    gas_price = None
    if args.gas_price_gwei is not None:
        gas_price = web3.to_wei(Decimal(str(args.gas_price_gwei)), "gwei")
    else:
        gas_price = web3.eth.gas_price

    try:
        estimated_gas = contract.functions.transfer(destination, amount_int).estimate_gas({"from": sender_address})
    except Web3Exception as exc:
        log.error("Gas estimation failed: %s", exc)
        return 1

    tx = contract.functions.transfer(destination, amount_int).build_transaction(
        {
            "from": sender_address,
            "nonce": nonce,
            "gas": int(estimated_gas * 1.2),
            "gasPrice": gas_price,
            "chainId": web3.eth.chain_id,
        }
    )

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
        "Sent transfer tx=%s amount=%s %s (%s base units) from=%s to=%s",
        tx_hash_hex,
        args.amount,
        symbol,
        amount_int,
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
