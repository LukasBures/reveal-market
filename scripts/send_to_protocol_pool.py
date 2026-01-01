#!/usr/bin/env python3
"""
Deposit ERC-20 collateral into the ProtocolPool via its `deposit(uint256)` function.

Defaults:
- sender/private key: scripts/generated/testnet_zenith_token_random_1764886505.txt
- token: Horizen testnet ZEN ERC-20
- pool: default ProtocolPool from .env.local (Horizen testnet)
- RPC: Horizen testnet public RPC
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

DEFAULT_RPC_URL = os.getenv("NEXT_PUBLIC_RPC_URL", "https://horizen-testnet.rpc.caldera.xyz/http")
DEFAULT_EXPLORER_URL = os.getenv("NEXT_PUBLIC_BLOCK_EXPLORER_URL", "https://horizen-testnet.explorer.caldera.xyz")
DEFAULT_KEYFILE = Path(__file__).resolve().parent / "generated" / "testnet_zen_funding_wallet_1764886505.txt"
DEFAULT_TOKEN_ADDRESS = "0x070040A826B586b58569750ED43cb5979b171e8d"  # ZEN ERC-20 on Horizen testnet  # noqa: S105
DEFAULT_POOL_ADDRESS = os.getenv("RM_PROTOCOL_POOL_ADDRESS", "0x613FC63d5FCAE6ED62694f3b7A171a72d18Cb429")
DEFAULT_TOKEN_AMOUNT = "2.0"  # noqa: S105

ERC20_ABI: list[dict[str, Any]] = [
    {
        "constant": False,
        "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
        "name": "approve",
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
        "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
        "name": "allowance",
        "outputs": [{"name": "remaining", "type": "uint256"}],
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

PROTOCOL_POOL_ABI: list[dict[str, Any]] = [
    {
        "constant": False,
        "inputs": [{"name": "amount", "type": "uint256"}],
        "name": "deposit",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }
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


def prepare_contract(web3: Web3, address: str, abi: list[dict[str, Any]]) -> Contract:
    checksum_address = web3.to_checksum_address(address)
    return web3.eth.contract(address=checksum_address, abi=abi)


def main() -> int:
    parser = argparse.ArgumentParser(description="Deposit ERC-20 collateral into the ProtocolPool.")
    parser.add_argument("--rpc-url", default=DEFAULT_RPC_URL, help="EVM RPC endpoint.")
    parser.add_argument("--explorer-base", default=DEFAULT_EXPLORER_URL, help="Block explorer base URL for logging.")
    parser.add_argument(
        "--pool",
        default=DEFAULT_POOL_ADDRESS,
        help="ProtocolPool address (defaults to RM_PROTOCOL_POOL_ADDRESS or known testnet pool).",
    )
    parser.add_argument(
        "--token",
        default=DEFAULT_TOKEN_ADDRESS,
        help="ERC-20 collateral token address (defaults to ZEN on Horizen testnet).",
    )
    parser.add_argument(
        "--amount",
        default=DEFAULT_TOKEN_AMOUNT,
        help="Human-readable token amount to deposit (defaults to DEFAULT_TOKEN_AMOUNT at top of file).",
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
    parser.add_argument("--skip-approve", action="store_true", help="Do not send approve; assumes allowance is set.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("send_to_protocol_pool")

    if not args.pool:
        log.error("Pool address is missing. Pass --pool.")
        return 1
    if not args.token:
        log.error("Token address is missing. Pass --token.")
        return 1
    if not args.amount:
        log.error("Amount is missing. Pass --amount.")
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
    pool_address = web3.to_checksum_address(args.pool)
    account = web3.eth.account.from_key(private_key)
    if account.address != sender_address:
        log.warning("Keyfile address (%s) does not match derived address (%s)", sender_address, account.address)
        sender_address = account.address

    token = prepare_contract(web3, args.token, ERC20_ABI)
    pool = prepare_contract(web3, pool_address, PROTOCOL_POOL_ABI)
    try:
        decimals = token.functions.decimals().call()
        symbol = token.functions.symbol().call()
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
            balance = token.functions.balanceOf(sender_address).call()
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
    gas_price = web3.eth.gas_price
    if args.gas_price_gwei is not None:
        gas_price = web3.to_wei(Decimal(str(args.gas_price_gwei)), "gwei")

    try:
        allowance = token.functions.allowance(sender_address, pool_address).call()
    except Web3Exception as exc:
        log.error("Failed to read allowance: %s", exc)
        return 1

    def send_and_wait(tx_dict):
        signed_tx = account.sign_transaction(tx_dict)
        raw_tx = getattr(signed_tx, "raw_transaction", None) or getattr(signed_tx, "rawTransaction", None)
        if raw_tx is None:
            raise RuntimeError("Signed transaction missing raw transaction bytes")
        tx_hash = web3.eth.send_raw_transaction(raw_tx)
        tx_hex = tx_hash.hex()
        log.info("Sent tx %s", tx_hex)
        explorer_url = f"{args.explorer_base.rstrip('/')}/tx/0x{tx_hex}"
        log.info("Explorer URL: %s", explorer_url)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
        log.info(
            "Mined status=%s block=%s gasUsed=%s",
            receipt.get("status"),
            receipt.get("blockNumber"),
            receipt.get("gasUsed"),
        )
        return tx_hex, receipt

    # Approve if needed
    if allowance < amount_int and not args.skip_approve:
        try:
            est = token.functions.approve(pool_address, amount_int).estimate_gas({"from": sender_address})
        except Web3Exception as exc:
            log.error("Gas estimation for approve failed: %s", exc)
            return 1
        approve_tx = token.functions.approve(pool_address, amount_int).build_transaction(
            {
                "from": sender_address,
                "nonce": nonce,
                "gas": int(est * 1.2),
                "gasPrice": gas_price,
                "chainId": web3.eth.chain_id,
            }
        )
        log.info("Allowance %s < %s %s; sending approve()", allowance, amount_int, symbol)
        try:
            send_and_wait(approve_tx)
        except Exception as exc:  # pragma: no cover - CLI path
            log.error("Approve failed: %s", exc)
            return 1
        nonce += 1
        try:
            allowance = token.functions.allowance(sender_address, pool_address).call()
        except Web3Exception:
            pass

    try:
        est = pool.functions.deposit(amount_int).estimate_gas({"from": sender_address})
    except Web3Exception as exc:
        log.error("Gas estimation for deposit failed: %s", exc)
        return 1

    deposit_tx = pool.functions.deposit(amount_int).build_transaction(
        {
            "from": sender_address,
            "nonce": nonce,
            "gas": int(est * 1.2),
            "gasPrice": gas_price,
            "chainId": web3.eth.chain_id,
        }
    )
    log.info("Depositing %s %s (%s base units) into ProtocolPool %s", args.amount, symbol, amount_int, pool_address)
    try:
        tx_hash, _ = send_and_wait(deposit_tx)
    except Exception as exc:  # pragma: no cover - CLI path
        log.error("Deposit failed: %s", exc)
        return 1

    log.info("Done. Deposit tx: %s", tx_hash)
    return 0


if __name__ == "__main__":
    sys.exit(main())
