from __future__ import annotations

import logging

from shared.logging import log_event
from shared.onchain import MARKET_FACTORY_ABI, VERIFIER_ABI, OnChainConfigurationError, get_async_web3, to_checksum

from .config import Settings

logger = logging.getLogger("reveal_market.api")


async def fetch_factory_markets(settings: Settings) -> list[str]:
    rpc_url = settings.rpc_url and str(settings.rpc_url)
    factory_address = settings.factory_address
    if not (rpc_url and factory_address):
        raise OnChainConfigurationError("Factory RPC configuration missing")

    web3 = get_async_web3(rpc_url)
    contract = web3.eth.contract(address=to_checksum(factory_address), abi=MARKET_FACTORY_ABI)
    addresses = await contract.functions.getMarkets().call()
    log_event(
        logger,
        logging.DEBUG,
        "api.onchain.get_markets",
        "fetched factory market addresses",
        count=len(addresses),
    )
    return addresses


def _normalize_bytes32(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return "0x" + value.hex()
    hex_value = getattr(value, "hex", None)
    if callable(hex_value):
        try:
            result = hex_value()
            return result if isinstance(result, str) else str(result)
        except Exception:
            return None
    return str(value)


async def validate_verifier_circuit_hash(settings: Settings) -> None:
    """Fail fast if the on-chain verifier circuit hash mismatches local configuration."""

    rpc_url = settings.rpc_url and str(settings.rpc_url)
    verifier_address = settings.verifier_address
    expected_hash = settings.circuit_hash
    if not (rpc_url and verifier_address and expected_hash):
        return
    web3 = get_async_web3(rpc_url)
    verifier = web3.eth.contract(address=to_checksum(verifier_address), abi=VERIFIER_ABI)
    onchain = await verifier.functions.circuitHash().call()
    onchain_hex = _normalize_bytes32(onchain)
    if not onchain_hex:
        raise OnChainConfigurationError("Verifier circuit hash unavailable")
    if onchain_hex.lower() != expected_hash.lower():
        raise OnChainConfigurationError(
            f"Verifier circuit hash mismatch: expected={expected_hash}, onchain={onchain_hex}"
        )
