from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from eth_account.signers.local import LocalAccount
    from web3 import AsyncWeb3

logger = logging.getLogger("reveal_market.onchain")


class OnChainConfigurationError(RuntimeError):
    """Raised when required on-chain configuration is missing."""


@lru_cache(maxsize=1)
def get_async_web3(rpc_url: Optional[str]):
    """Return a cached AsyncWeb3 instance or raise if misconfigured."""

    if not rpc_url:
        raise OnChainConfigurationError("RM_RPC_URL is not configured")

    from web3 import AsyncWeb3 as _AsyncWeb3
    from web3.middleware import async_geth_poa_middleware
    from web3.providers.async_rpc import AsyncHTTPProvider

    provider = AsyncHTTPProvider(rpc_url)
    web3 = _AsyncWeb3(provider)

    try:
        web3.middleware_onion.inject(async_geth_poa_middleware, layer=0)
    except ValueError:
        # Middleware already installed; ignore.
        pass

    return web3


def load_account(private_key: Optional[str]):
    """Create a signing account from the provided private key."""

    if not private_key:
        raise OnChainConfigurationError("RM_WALLET_PRIVATE_KEY is not configured")

    try:
        from eth_account import Account  # imported lazily

        account = Account.from_key(private_key)
    except ValueError as exc:  # pragma: no cover - defensive
        raise OnChainConfigurationError("Invalid private key provided") from exc
    return account


def to_checksum(address: Optional[str]) -> str:
    """Convert address to checksum format, raising if invalid."""

    if not address:
        raise OnChainConfigurationError("Required contract address missing")
    try:
        from web3 import AsyncWeb3 as _AsyncWeb3

        return _AsyncWeb3.to_checksum_address(address)
    except ValueError as exc:  # pragma: no cover - defensive
        raise OnChainConfigurationError(f"Invalid address: {address}") from exc
