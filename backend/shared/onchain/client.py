from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    pass

logger = logging.getLogger("reveal_market.onchain")

_async_web3_instance = None
_async_web3_lock = threading.Lock()


class OnChainConfigurationError(RuntimeError):
    """Raised when required on-chain configuration is missing."""


def _import_async_http_provider():
    try:
        from web3.providers.rpc import AsyncHTTPProvider  # web3>=7
    except ModuleNotFoundError:  # pragma: no cover - compatibility with older web3
        try:
            from web3.providers.async_rpc import AsyncHTTPProvider  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:  # pragma: no cover - defensive
            raise OnChainConfigurationError("AsyncHTTPProvider is unavailable; check web3 installation") from exc
    return AsyncHTTPProvider


def _rpc_timeout_seconds() -> float | None:
    raw = os.getenv("RM_RPC_HTTP_TIMEOUT_SECONDS")
    if raw is None or raw == "":
        return 10.0
    try:
        value = float(raw)
    except ValueError:
        return 10.0
    if value <= 0:
        return None
    return value


def get_async_web3(rpc_url: str | None):
    """Return a singleton AsyncWeb3 instance or raise if misconfigured.

    Use ``reset_async_web3()`` to force re-creation (e.g. after connection errors or in tests).
    """
    global _async_web3_instance

    if not rpc_url:
        raise OnChainConfigurationError("RM_RPC_URL is not configured")

    with _async_web3_lock:
        if _async_web3_instance is not None:
            return _async_web3_instance

        from web3 import AsyncWeb3 as _AsyncWeb3

        async_http_provider = _import_async_http_provider()

        try:
            from web3.middleware import async_geth_poa_middleware  # type: ignore[attr-defined]
        except (ModuleNotFoundError, ImportError, AttributeError):  # pragma: no cover - compatible with older web3
            async_geth_poa_middleware = None
        try:
            from web3.middleware import ExtraDataToPOAMiddleware  # web3>=7

            extra_data_to_poa_middleware = ExtraDataToPOAMiddleware
        except (ModuleNotFoundError, ImportError, AttributeError):  # pragma: no cover - optional
            extra_data_to_poa_middleware = None  # ruff: disable=N806

        timeout_seconds = _rpc_timeout_seconds()
        if timeout_seconds is None:
            provider = async_http_provider(rpc_url)
        else:
            provider = async_http_provider(rpc_url, request_kwargs={"timeout": timeout_seconds})
        web3: _AsyncWeb3 = _AsyncWeb3(provider)

        if async_geth_poa_middleware:
            try:
                web3.middleware_onion.inject(async_geth_poa_middleware, layer=0)
            except ValueError:
                logger.debug("POA middleware already installed; skipping injection")
        elif extra_data_to_poa_middleware:
            try:
                web3.middleware_onion.inject(extra_data_to_poa_middleware, layer=0)
            except ValueError:
                logger.debug("POA middleware already installed; skipping injection")

        _async_web3_instance = web3
        return web3


def reset_async_web3() -> None:
    """Invalidate the cached AsyncWeb3 singleton, forcing re-creation on next call.

    Useful for tests and for connection recovery after RPC failures.
    """
    global _async_web3_instance
    with _async_web3_lock:
        _async_web3_instance = None


def load_account(private_key: str | None):
    """Create a signing account from the provided private key."""

    if not private_key:
        raise OnChainConfigurationError("RM_WALLET_PRIVATE_KEY is not configured")

    try:
        from eth_account import Account  # imported lazily

        account = Account.from_key(private_key)
    except ValueError as exc:  # pragma: no cover - defensive
        raise OnChainConfigurationError("Invalid private key provided") from exc
    return account


def to_checksum(address: str | None) -> str:
    """Convert address to checksum format, raising if invalid."""

    if not address:
        raise OnChainConfigurationError("Required contract address missing")
    try:
        from web3 import AsyncWeb3 as _AsyncWeb3

        return _AsyncWeb3.to_checksum_address(address)
    except ValueError as exc:  # pragma: no cover - defensive
        raise OnChainConfigurationError(f"Invalid address: {address}") from exc
