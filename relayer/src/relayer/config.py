import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing env var: {name}")
    return val


@dataclass
class RelayerConfig:
    rpc_url: str
    chain_id: int
    relayer_private_key: str
    relayer_escrow_address: str
    host: str
    port: int


def load_config() -> RelayerConfig:
    return RelayerConfig(
        rpc_url=_require_env("RPC_URL"),
        chain_id=int(_require_env("CHAIN_ID")),
        relayer_private_key=_require_env("RELAYER_PRIVATE_KEY"),
        relayer_escrow_address=_require_env("RELAYER_ESCROW_ADDRESS"),
        host=_require_env("RELAYER_HOST"),
        port=int(_require_env("RELAYER_PORT")),
    )
