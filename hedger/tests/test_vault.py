from __future__ import annotations

from decimal import Decimal

import pytest
from app.vault import BaseLpVaultClient, OnChainLpVaultClient, VaultTxConfig


@pytest.mark.asyncio
async def test_base_vault_updates_utilization():
    client = BaseLpVaultClient("0x0000000000000000000000000000000000000000")
    await client.borrow_for_hedge(Decimal("1000"))
    util = await client.current_utilization()
    assert util > 0
    await client.repay_from_hedge(Decimal("1000"))
    util_after = await client.current_utilization()
    assert util_after <= util


def test_onchain_vault_requires_config():
    tx_cfg = VaultTxConfig(
        rpc_url="http://localhost:8545",
        chain_id=1337,
        private_key="0x" + "11" * 32,
        sender="0x0000000000000000000000000000000000000001",
    )
    # Construction should not raise even without a live chain; methods would fail at runtime.
    client = OnChainLpVaultClient("0x0000000000000000000000000000000000000002", tx_cfg)
    assert client.tx_config.chain_id == 1337
