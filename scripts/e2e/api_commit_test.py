#!/usr/bin/env python3
"""
API Commit Test — End-to-end flow mimicking the frontend's exact commit path.

Unlike commit_bet.py (direct on-chain), this script goes through the production API:
  1. Check wallet ZEN balance & escrow balance
  2. Deposit to escrow if needed
  3. List available markets via GET /events
  4. Get pricing quote via POST /pricing/quote
  5. Build wallet commit signature (same format as frontend/lib/signature-messages.ts)
  6. Submit commit via POST /trade/commit with X-Wallet-Signature header
  7. Poll /trade/status until relayer job succeeds
  8. Verify position appears in GET /positions

Usage:
  export API_URL=https://api.revealmarket.xyz
  export TEST_WALLET_KEY=<private key>
  python api_commit_test.py [--market-id <event_id>] [--skip-deposit]
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import HTTPProvider, Web3

try:
    from web3.middleware import geth_poa_middleware as _poa_middleware
except ImportError:
    _poa_middleware = None

try:
    from web3.middleware import ExtraDataToPOAMiddleware
except ImportError:
    ExtraDataToPOAMiddleware = None

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
API_URL = os.getenv("API_URL", "https://api.revealmarket.xyz")
RPC_URL = os.getenv("RM_RPC_URL", "https://horizen-testnet.rpc.caldera.xyz/http")
INTERNAL_SECRET =<REDACTED>
TEST_WALLET_KEY = os.environ["TEST_WALLET_KEY"]
STAKE_ZEN = Decimal("0.1000")

ZEN_TOKEN = os.getenv("ZEN_TOKEN_ADDRESS", "0x070040A826B586b58569750ED43cb5979b171e8d")
RELAYER_ESCROW = os.getenv("RM_RELAYER_ESCROW_ADDRESS", "0x5b0fA47675D07b018E2151d49d4aECc71b47E47D")

log = logging.getLogger("api-e2e")

# ---------------------------------------------------------------------------
# Minimal ABIs (inlined to avoid importing utils.py which requires many env vars)
# ---------------------------------------------------------------------------

ERC20_ABI: list[dict[str, Any]] = [
    {
        "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

ESCROW_ABI: list[dict[str, Any]] = [
    {
        "inputs": [{"name": "amount", "type": "uint256"}],
        "name": "deposit",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


# ---------------------------------------------------------------------------
# Web3 helpers
# ---------------------------------------------------------------------------


def build_web3() -> Web3:
    web3 = Web3(HTTPProvider(RPC_URL, request_kwargs={"timeout": 30}))
    if _poa_middleware is not None:
        web3.middleware_onion.inject(_poa_middleware, layer=0)
    elif ExtraDataToPOAMiddleware is not None:
        web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if not web3.is_connected():
        raise ConnectionError(f"Failed to connect to RPC at {RPC_URL}")
    return web3


def send_tx(web3: Web3, private_key: str, tx_func, *, label: str = "tx") -> dict:
    account = Account.from_key(private_key)
    sender = account.address
    nonce = web3.eth.get_transaction_count(sender, "pending")
    gas_price = web3.eth.gas_price
    est = tx_func.estimate_gas({"from": sender})
    tx = tx_func.build_transaction(
        {
            "from": sender,
            "nonce": nonce,
            "gas": int(est * 1.3),
            "gasPrice": gas_price,
            "chainId": web3.eth.chain_id,
        }
    )
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    tx_hash = web3.eth.send_raw_transaction(raw)
    tx_hex = tx_hash.hex()
    log.info("[%s] Sent tx: 0x%s", label, tx_hex)
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.get("status") != 1:
        raise RuntimeError(f"[{label}] Transaction reverted! tx=0x{tx_hex}")
    log.info("[%s] Mined: block=%s gas=%s", label, receipt.get("blockNumber"), receipt.get("gasUsed"))
    return dict(receipt)


def wei_to_zen(wei: int) -> str:
    return f"{Decimal(wei) / Decimal(10**18):.4f} ZEN"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def api_get(path: str, *, headers: dict | None = None) -> httpx.Response:
    url = f"{API_URL}{path}"
    h: dict[str, str] = {}
    if INTERNAL_SECRET:
        h["X-Internal-Secret"] = INTERNAL_SECRET
    if headers:
        h.update(headers)
    return httpx.get(url, headers=h, timeout=30)


def api_post(path: str, data: dict, *, headers: dict | None = None) -> httpx.Response:
    url = f"{API_URL}{path}"
    h: dict[str, str] = {"Content-Type": "application/json"}
    if INTERNAL_SECRET:
        h["X-Internal-Secret"] = INTERNAL_SECRET
    if headers:
        h.update(headers)
    return httpx.post(url, json=data, headers=h, timeout=30)


# ---------------------------------------------------------------------------
# Signature message builder — mirrors frontend/lib/signature-messages.ts
# ---------------------------------------------------------------------------


def format_decimal(value: float | str | None, decimals: int = 4) -> str:
    if value is None:
        return "n/a"
    numeric = float(value)
    if not math.isfinite(numeric):
        return "n/a"
    factor = 10**decimals
    truncated = math.floor(numeric * factor) / factor
    return f"{truncated:.{decimals}f}"


def build_commit_signature_message(quote: dict, wallet_address: str) -> str:
    wallet = wallet_address.lower()
    quote_id = quote.get("quote_id") or ""
    market_id = quote.get("market_id") or "n/a"
    outcome_id = quote.get("outcome_id")
    outcome_str = "n/a" if outcome_id is None else str(int(outcome_id))
    stake_zen = format_decimal(quote.get("stake_zen"))
    payout_zen = format_decimal(quote.get("payout_zen"))
    return "\n".join(
        [
            "RevealMarket Buy Confirmation",
            "",
            f"Market ID: {market_id}",
            f"Outcome ID: {outcome_str}",
            f"You pay: {stake_zen} ZEN",
            f"You can win: {payout_zen} ZEN",
            f"Quote ID: {quote_id}",
            f"Wallet: {wallet}",
            "",
            "By signing, you authorize RevealMarket to submit this buy.",
        ]
    )


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="API-based E2E commit test")
    parser.add_argument("--market-id", help="Specific event_id to trade on")
    parser.add_argument("--skip-deposit", action="store_true", help="Skip escrow deposit step")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    account = Account.from_key(TEST_WALLET_KEY)
    wallet = account.address
    all_ok = True

    def ok(label: str, condition: bool, detail: str = "") -> bool:
        nonlocal all_ok
        if condition:
            log.info("  [PASS] %s %s", label, detail)
        else:
            log.error("  [FAIL] %s %s", label, detail)
        all_ok &= condition
        return condition

    # ─── Step 0: Health check ──────────────────────────────────────────────
    log.info("=" * 60)
    log.info("  Step 0: Health Check")
    log.info("=" * 60)
    log.info("  API: %s", API_URL)
    log.info("  Wallet: %s", wallet)

    resp = api_get("/healthz")
    ok("API healthy", resp.status_code == 200, f"status={resp.status_code}")

    # ─── Step 1: Check wallet ZEN balance ──────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("  Step 1: Check Wallet Balances")
    log.info("=" * 60)

    web3 = build_web3()
    zen = web3.eth.contract(address=web3.to_checksum_address(ZEN_TOKEN), abi=ERC20_ABI)
    zen_balance = zen.functions.balanceOf(web3.to_checksum_address(wallet)).call()
    log.info("  ZEN balance: %s", wei_to_zen(zen_balance))

    escrow_contract = web3.eth.contract(address=web3.to_checksum_address(RELAYER_ESCROW), abi=ESCROW_ABI)
    escrow_balance = escrow_contract.functions.balanceOf(web3.to_checksum_address(wallet)).call()
    log.info("  Escrow balance: %s", wei_to_zen(escrow_balance))

    stake_wei = int(STAKE_ZEN * Decimal(10**18))

    # ─── Step 2: Deposit to escrow if needed ───────────────────────────────
    if not args.skip_deposit and escrow_balance < stake_wei:
        log.info("")
        log.info("=" * 60)
        log.info("  Step 2: Deposit to Escrow")
        log.info("=" * 60)

        deposit_amount = stake_wei - escrow_balance
        ok("Sufficient ZEN for deposit", zen_balance >= deposit_amount, f"need {wei_to_zen(deposit_amount)}")
        if zen_balance < deposit_amount:
            log.error("Insufficient ZEN balance to deposit. Fund wallet %s first.", wallet)
            return 1

        allowance = zen.functions.allowance(
            web3.to_checksum_address(wallet), web3.to_checksum_address(RELAYER_ESCROW)
        ).call()
        if allowance < deposit_amount:
            log.info("  Approving ZEN for escrow...")
            send_tx(
                web3,
                TEST_WALLET_KEY,
                zen.functions.approve(web3.to_checksum_address(RELAYER_ESCROW), deposit_amount),
                label="approve-zen",
            )

        log.info("  Depositing %s to escrow...", wei_to_zen(deposit_amount))
        send_tx(
            web3,
            TEST_WALLET_KEY,
            escrow_contract.functions.deposit(deposit_amount),
            label="escrow-deposit",
        )

        escrow_balance = escrow_contract.functions.balanceOf(web3.to_checksum_address(wallet)).call()
        ok("Escrow balance sufficient", escrow_balance >= stake_wei, f"balance={wei_to_zen(escrow_balance)}")
    else:
        log.info("  Escrow balance sufficient, skipping deposit.")

    # ─── Step 3: List available markets ────────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("  Step 3: Find Active Market")
    log.info("=" * 60)

    market_id = args.market_id
    market: dict[str, Any] = {}
    if not market_id:
        resp = api_get("/events?status=commit")
        if not ok("Events endpoint reachable", resp.status_code == 200, f"status={resp.status_code}"):
            return 1
        events = resp.json()
        now = datetime.now(UTC)
        # Events are groups; tradeable markets are nested in markets[].
        # Pick a sub-market that has a condition_id (needed for CLOB pricing).
        for event in events:
            if event.get("resolved_at"):
                continue
            closes_at_str = event.get("closes_at")
            if not closes_at_str:
                continue
            try:
                closes_at = datetime.fromisoformat(closes_at_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if closes_at <= now:
                continue
            sub_markets = event.get("markets") or []
            for sm in sub_markets:
                sm_status = sm.get("status")
                if sm_status not in (None, "commit", "active", "open"):
                    continue
                if sm.get("condition_id") and sm.get("event_id"):
                    market = sm
                    market_id = str(sm["event_id"])
                    break
            if market_id:
                break
        if not ok("Active sub-market found", bool(market_id), f"total_events={len(events)}"):
            log.error("No active markets with condition_id available for testing.")
            return 1
    else:
        resp = api_get(f"/events/{market_id}")
        if not ok("Market found", resp.status_code == 200, f"event_id={market_id}"):
            return 1
        market = resp.json()

    log.info("  Market: %s", market.get("title", market_id))
    log.info("  Event ID (market_id): %s", market_id)
    log.info("  Condition ID: %s", market.get("condition_id", "n/a"))
    log.info("  Address: %s", market.get("market_address", "pending"))

    # ─── Step 4: Get pricing quote ─────────────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("  Step 4: Get Pricing Quote")
    log.info("=" * 60)

    quote_payload: dict[str, Any] = {
        "stake_zen": str(STAKE_ZEN),
        "market_id": market_id,
        "wallet_address": wallet,
        "outcome_id": 0,
    }
    if market.get("market_address"):
        quote_payload["market_address"] = market["market_address"]

    resp = api_post("/pricing/quote", quote_payload)
    if not ok("Quote received", resp.status_code == 200, f"status={resp.status_code}"):
        log.error("Quote response: %s", resp.text[:500])
        return 1

    quote_data = resp.json()
    quote = quote_data.get("quote") or quote_data
    quote_id = quote.get("quote_id")
    log.info("  Quote ID: %s", quote_id)
    log.info("  Stake: %s ZEN", quote.get("stake_zen"))
    log.info("  Payout: %s ZEN", quote.get("payout_zen"))
    log.info("  FX: %s", quote.get("zen_usd"))
    log.info("  Expires: %s", quote.get("expires_at"))

    ok("Quote has ID", bool(quote_id))
    ok("Quote has payout", quote.get("payout_zen") is not None)

    # ─── Step 5: Build wallet commit signature ─────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("  Step 5: Sign Commit Message")
    log.info("=" * 60)

    message = build_commit_signature_message(quote, wallet)
    log.info("  Message:\n%s", message)

    signable = encode_defunct(text=message)
    signed = account.sign_message(signable)
    wallet_signature = signed.signature.hex()
    if not wallet_signature.startswith("0x"):
        wallet_signature = "0x" + wallet_signature
    log.info("  Signature: %s...%s", wallet_signature[:18], wallet_signature[-8:])

    # ─── Step 6: Submit commit ─────────────────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("  Step 6: Submit Commit via API")
    log.info("=" * 60)

    commit_payload: dict[str, Any] = {"quote_id": quote_id}
    resp = api_post(
        "/trade/commit",
        commit_payload,
        headers={"X-Wallet-Signature": wallet_signature},
    )
    if not ok("Commit accepted", resp.status_code == 200, f"status={resp.status_code}"):
        log.error("Commit response: %s", resp.text[:500])
        return 1

    commit_data = resp.json()
    tx_hash = commit_data.get("tx_hash")
    relayer_job_id = commit_data.get("relayer_job_id")
    relayer_status = commit_data.get("relayer_status") or commit_data.get("status")
    log.info("  TX hash: %s", tx_hash)
    log.info("  Relayer job ID: %s", relayer_job_id)
    log.info("  Relayer status: %s", relayer_status)
    log.info("  Ticket ID: %s", commit_data.get("ticket_id"))

    # ─── Step 7: Poll trade status ─────────────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("  Step 7: Poll Transaction Status")
    log.info("=" * 60)

    poll_id = relayer_job_id or tx_hash
    if not poll_id:
        log.warning("No job_id or tx_hash to poll — commit may have failed silently.")
    else:
        deadline = time.time() + 120
        final_status = None
        final_tx_hash = None
        while time.time() < deadline:
            params = {}
            if relayer_job_id:
                params["job_id"] = relayer_job_id
            if tx_hash:
                params["tx_hash"] = tx_hash

            query = "&".join(f"{k}={v}" for k, v in params.items())
            resp = api_get(f"/trade/status?{query}")
            if resp.status_code == 200:
                status_data = resp.json()
                final_status = status_data.get("status")
                final_tx_hash = status_data.get("tx_hash") or final_tx_hash
                log.info("  Status: %s | TX: %s", final_status, final_tx_hash)
                if final_status in ("succeeded", "confirmed", "mined", "completed"):
                    break
                if final_status in ("failed", "dead", "deadletter"):
                    log.error("Relayer job failed: %s", status_data)
                    break
            else:
                log.warning("  Status poll returned %s", resp.status_code)
            time.sleep(3)

        ok(
            "Transaction confirmed",
            final_status in ("succeeded", "confirmed", "mined", "completed"),
            f"status={final_status}",
        )
        if final_tx_hash and len(final_tx_hash) == 66 and final_tx_hash.startswith("0x"):
            tx_hash = final_tx_hash
            log.info("  Final TX hash: %s", tx_hash)

    # ─── Step 8: Verify on-chain ───────────────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("  Step 8: Verify On-Chain")
    log.info("=" * 60)

    if tx_hash and len(tx_hash) == 66 and tx_hash.startswith("0x"):
        try:
            receipt = web3.eth.get_transaction_receipt(tx_hash)
            on_chain_status = receipt.get("status", -1)
            block = receipt.get("blockNumber", 0)
            log.info("  TX mined: status=%s block=%s gas=%s", on_chain_status, block, receipt.get("gasUsed", 0))
            ok("TX successful on-chain", on_chain_status == 1)
        except Exception as e:
            ok("TX receipt found", False, str(e))
    else:
        log.warning("  No valid tx hash to verify on-chain (hash=%s)", tx_hash)

    # ─── Step 9: Check position in dashboard ───────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("  Step 9: Verify Position in Dashboard")
    log.info("=" * 60)

    resp = api_get(f"/positions?wallet={wallet}")
    if ok("Positions endpoint reachable", resp.status_code == 200):
        positions_data = resp.json()
        if isinstance(positions_data, dict):
            positions = positions_data.get("positions", [])
        else:
            positions = positions_data
        matching = [p for p in positions if p.get("market_id") == market_id or p.get("event_id") == market_id]
        ok("Position appears in dashboard", len(matching) > 0, f"total_positions={len(positions)}")
        if matching:
            pos = matching[0]
            log.info("  Position status: %s", pos.get("status"))
            log.info("  Position tx_hash: %s", pos.get("tx_hash"))
            log.info("  Position stake: %s ZEN", pos.get("stake_zen"))
            pos_tx = pos.get("tx_hash")
            if pos_tx:
                ok("Position has valid tx_hash", len(pos_tx) == 66 and pos_tx.startswith("0x"))

    # ─── Summary ───────────────────────────────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("  SUMMARY")
    log.info("=" * 60)
    log.info("  Wallet: %s", wallet)
    log.info("  Market: %s", market_id)
    log.info("  TX Hash: %s", tx_hash)

    if all_ok:
        log.info("")
        log.info("ALL CHECKS PASSED — API commit flow verified!")
        return 0
    else:
        log.error("SOME CHECKS FAILED — Review output above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
