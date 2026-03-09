#!/usr/bin/env python3
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from web3 import Web3
from web3.providers.rpc import HTTPProvider

RPC_URL = os.getenv("RM_RPC_URL", "https://horizen.calderachain.xyz/http")
RPC_TIMEOUT_SECONDS = 10
ROOT = Path(__file__).resolve().parents[2]
ZEN_BROADCAST_DIR = ROOT / "contracts" / "zen" / "broadcast" / "Deploy.s.sol"
OUT_DIR = ROOT / "contracts" / "zen" / "out"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _find_latest_deploy() -> Path | None:
    candidates = list(ZEN_BROADCAST_DIR.glob("**/run-latest.json"))
    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    fallback = list(ZEN_BROADCAST_DIR.glob("**/run-*.json"))
    if fallback:
        return max(fallback, key=lambda p: p.stat().st_mtime)
    return None


def _extract_addresses(run_path: Path) -> tuple[str, str]:
    data = _load_json(run_path)
    txs = data.get("transactions", [])
    factory = None
    pool = None
    for tx in txs:
        name = tx.get("contractName")
        addr = tx.get("contractAddress")
        if name == "MarketFactory" and addr and factory is None:
            factory = addr
        if name == "ProtocolPool" and addr and pool is None:
            pool = addr
    if not factory or not pool:
        raise RuntimeError("Could not find MarketFactory or ProtocolPool in deployment artifacts.")
    return factory, pool


def _abi(path: Path) -> list[dict[str, Any]]:
    data = _load_json(path)
    return data["abi"]


def _format_ts(ts: int) -> str:
    if ts == 0:
        return "-"
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _format_amount(value: int, decimals: int) -> str:
    scaled = value / (10**decimals)
    return f"{scaled:,.6f}"


def _phase_name(phase: int) -> str:
    return {0: "Commit", 1: "Locked", 2: "Settled", 3: "Cancelled"}.get(phase, f"Unknown({phase})")


def _load_contract(w3: Web3, addr: str, abi_path: Path):
    return w3.eth.contract(address=Web3.to_checksum_address(addr), abi=_abi(abi_path))


def _market_ids(factory) -> list[int]:
    next_id = factory.functions.nextMarketId().call()
    return list(range(1, next_id))


def _safe_call(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def main() -> int:
    deploy_path = _find_latest_deploy()
    if not deploy_path:
        print("ERROR: No deployment artifacts found under contracts/zen/broadcast/Deploy.s.sol.", file=sys.stderr)
        return 1

    factory_addr, pool_addr = _extract_addresses(deploy_path)

    w3 = Web3(HTTPProvider(RPC_URL, request_kwargs={"timeout": RPC_TIMEOUT_SECONDS}))
    if not w3.is_connected():
        print(f"ERROR: Could not connect to RPC: {RPC_URL}", file=sys.stderr)
        return 1

    factory = _load_contract(w3, factory_addr, OUT_DIR / "MarketFactory.sol" / "MarketFactory.json")
    pool = _load_contract(w3, pool_addr, OUT_DIR / "ProtocolPool.sol" / "ProtocolPool.json")
    market_abi_path = OUT_DIR / "RevealMarket.sol" / "RevealMarket.json"
    erc20_abi_path = OUT_DIR / "ERC20.sol" / "ERC20.json"

    market_ids = _market_ids(factory)
    total_tickets = 0
    total_liability = 0
    total_escrow = 0
    live_markets: list[dict[str, Any]] = []
    for market_id in market_ids:
        addr = factory.functions.marketForId(market_id).call()
        market = _load_contract(w3, addr, market_abi_path)

        state = _safe_call(lambda market=market: market.functions.marketState().call(), None)
        if state:
            _, tickets, phase, commit_deadline, _ = state
        else:
            tickets = _safe_call(lambda market=market: market.functions.nextTicketId().call(), 0)
            phase = _safe_call(lambda market=market: market.functions.phase().call(), None)
            commit_deadline = _safe_call(lambda market=market: market.functions.commitDeadline().call(), 0)

        escrow = _safe_call(lambda market=market: market.functions.totalEscrow().call(), 0)
        liability = _safe_call(lambda market=market: market.functions.totalLiability().call(), 0)
        claim_deadline = _safe_call(lambda market=market: market.functions.claimDeadline().call(), 0)

        total_tickets += tickets
        total_escrow += escrow
        total_liability += liability

        if tickets > 0 and phase in (0, 1):
            live_markets.append(
                {
                    "id": market_id,
                    "address": addr,
                    "phase": _phase_name(phase),
                    "tickets": tickets,
                    "escrow": escrow,
                    "liability": liability,
                    "commit_deadline": commit_deadline,
                    "claim_deadline": claim_deadline,
                }
            )

    token_addr = pool.functions.COLLATERAL_TOKEN().call()
    token = _load_contract(w3, token_addr, erc20_abi_path)
    decimals = _safe_call(lambda: token.functions.decimals().call(), 18)
    symbol = _safe_call(lambda: token.functions.symbol().call(), "TOKEN")
    pool_balance = token.functions.balanceOf(Web3.to_checksum_address(pool_addr)).call()
    total_consumed_liability = _safe_call(
        lambda: sum(
            pool.functions.consumedLiability(Web3.to_checksum_address(m["address"])).call() for m in live_markets
        ),
        0,
    )

    print("RevealMarket Monitoring Report")
    print(f"RPC: {RPC_URL}")
    print(f"Factory: {Web3.to_checksum_address(factory_addr)}")
    print(f"ProtocolPool: {Web3.to_checksum_address(pool_addr)}")
    print(f"Collateral Token: {Web3.to_checksum_address(token_addr)} ({symbol})")
    print("")
    total_markets = factory.functions.nextMarketId().call() - 1
    print(f"Markets Deployed: {total_markets}")
    print(f"Markets Scanned: {len(market_ids)}")
    print(f"Tickets Purchased (total positions): {total_tickets}")
    print(f"Total Market Escrow: {_format_amount(total_escrow, decimals)} {symbol}")
    print(f"Total Market Liability: {_format_amount(total_liability, decimals)} {symbol}")
    print(f"ProtocolPool Consumed Liability (live): {_format_amount(total_consumed_liability, decimals)} {symbol}")
    print(f"ProtocolPool Balance: {_format_amount(pool_balance, decimals)} {symbol}")
    print("")

    if not live_markets:
        print("No live markets with tickets.")
        return 0

    headers = [
        "MarketId",
        "Address",
        "Phase",
        "Tickets",
        "Liability",
        "Escrow",
        "Commit Deadline",
        "Claim Deadline",
    ]

    headers = [
        "MarketId",
        "Address",
        "Phase",
        "Tickets",
        "Liability",
        "Escrow",
        "Commit Deadline",
        "Claim Deadline",
    ]
    rows = []
    for m in live_markets:
        rows.append(
            [
                str(m["id"]),
                Web3.to_checksum_address(m["address"]),
                m["phase"],
                str(m["tickets"]),
                _format_amount(m["liability"], decimals),
                _format_amount(m["escrow"], decimals),
                _format_ts(m["commit_deadline"]),
                _format_ts(m["claim_deadline"]),
            ]
        )

    col_widths = [max(len(row[i]) for row in [headers] + rows) for i in range(len(headers))]

    def _fmt_row(values: list[str]) -> str:
        return " | ".join(values[i].ljust(col_widths[i]) for i in range(len(values)))

    print(_fmt_row(headers))
    print("-+-".join("-" * w for w in col_widths))
    for row in rows:
        print(_fmt_row(row))

    return 0


if __name__ == "__main__":
    sys.exit(main())
