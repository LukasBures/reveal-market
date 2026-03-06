"""Shared utilities for end-to-end integration test scripts."""

from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import HTTPProvider, Web3
from web3.contract.contract import Contract

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

RPC_URL = os.getenv("RM_RPC_URL", "https://horizen-testnet.rpc.caldera.xyz/http")
CHAIN_ID = int(os.getenv("CHAIN_ID", "2651420"))
EXPLORER_URL = os.getenv("NEXT_PUBLIC_BLOCK_EXPLORER_URL", "https://horizen-testnet.explorer.caldera.xyz")

# Contract addresses
ZEN_TOKEN = os.getenv("ZEN_TOKEN_ADDRESS", "0x070040A826B586b58569750ED43cb5979b171e8d")
FACTORY = os.getenv("RM_FACTORY_ADDRESS", "0x07e13179E5231B3823f26ECBA2750834cBAfC9d3")
PROTOCOL_POOL = os.getenv("RM_PROTOCOL_POOL_ADDRESS", "0x314E44e894DeFDDb4c7337F7031901Ef7Bbab2E2")
RELAYER_ESCROW = os.getenv("RM_RELAYER_ESCROW_ADDRESS", "0x5b0fA47675D07b018E2151d49d4aECc71b47E47D")
VERIFIER = os.getenv("RM_VERIFIER_ADDRESS", "0xC319CC9576dAc33440ab2b7013D067CbD88aBd07")
ORACLE_ADDRESS = os.getenv("RM_ORACLE_ADDRESS", "0x0F3d0f9274fA6AAEEbc493EdD44d2979BD75F369")
AUTH_SIGNER_ADDRESS = os.getenv("RM_AUTHORIZATION_SIGNER", "0x38C57472479fe7bB4C87e7A4BB23c7AAf10595Fd")
CIRCUIT_HASH = os.getenv("PROVER_CIRCUIT_HASH", "0x181e1866c82c6c72f18cd61723f1f61cd0a02224250b988af5a3f32863f2b157")

# Private keys — must be set via environment variables; no defaults to avoid leaking keys.
FUNDING_WALLET_KEY = os.environ["FUNDING_WALLET_KEY"]
DEPLOYER_KEY = os.environ["DEPLOYER_KEY"]
TEST_ACCOUNT_KEY = os.environ["TEST_ACCOUNT_KEY"]
ORACLE_KEY = os.environ["ORACLE_KEY"]
AUTH_SIGNER_KEY = os.environ["RM_AUTHORIZATION_SIGNER_PRIVATE_KEY"]
RELAYER_KEY = os.environ["RELAYER_PRIVATE_KEY"]

# Service URLs
API_URL = os.getenv("API_URL", "http://localhost:8000")
RELAYER_URL = os.getenv("RELAYER_URL", "http://localhost:8088")
PROVER_URL = os.getenv("PROVER_URL", "http://localhost:8085")
HEDGER_URL = os.getenv("HEDGER_URL", "http://localhost:8090")

# Auth tokens
INTERNAL_SECRET =<REDACTED>
RELAYER_BEARER = os.getenv("RELAYER_BEARER_TOKEN", "REDACTED")
PROVER_SECRET =<REDACTED>

# State file for passing data between scripts
SCRIPTS_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPTS_DIR / "e2e_state.json"

log = logging.getLogger("e2e")

# ---------------------------------------------------------------------------
# Minimal ABIs
# ---------------------------------------------------------------------------

ERC20_ABI: list[dict[str, Any]] = [
    {
        "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
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
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
]

FACTORY_ABI: list[dict[str, Any]] = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "oracle", "type": "address"},
                    {"name": "verifier", "type": "address"},
                    {"name": "circuitHash", "type": "bytes32"},
                    {"name": "commitDeadline", "type": "uint256"},
                    {"name": "fixedTicketSize", "type": "uint256"},
                    {"name": "maxCommitments", "type": "uint256"},
                    {"name": "authorizationSigner", "type": "address"},
                    {"name": "protocolLiabilityCap", "type": "uint256"},
                ],
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "createMarket",
        "outputs": [{"name": "market", "type": "address"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "nextMarketId",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "verifier", "type": "address"}, {"name": "approved", "type": "bool"}],
        "name": "setVerifierApproval",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "verifier", "type": "address"}],
        "name": "approvedVerifiers",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "marketId", "type": "uint256"}],
        "name": "marketAddress",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "rakeBps", "type": "uint256"}],
        "name": "setGlobalRakeBps",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "globalRakeBps",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

POOL_ABI: list[dict[str, Any]] = [
    {
        "inputs": [{"name": "amount", "type": "uint256"}],
        "name": "deposit",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalAssets",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "idleLiquidity",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "market", "type": "address"}],
        "name": "consumedLiability",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "sharesToRedeem", "type": "uint256"}, {"name": "minAssets", "type": "uint256"}],
        "name": "lpWithdraw",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "lp", "type": "address"}],
        "name": "lpShareBalance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "lp", "type": "address"}],
        "name": "unlockedShares",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "lp", "type": "address"}],
        "name": "maxRedeemable",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "shares", "type": "uint256"}],
        "name": "convertToAssets",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalShares",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "reservedTotal",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "name": "withdraw",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "market", "type": "address"}],
        "name": "forceReleaseLiability",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "paused", "type": "bool"}],
        "name": "setDrawsPaused",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "drawsPaused",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "owner",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "LOCK_DURATION",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "market", "type": "address"}],
        "name": "reservedLiability",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "lp", "type": "address"}],
        "name": "grantEmergencyUnlock",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "lp", "type": "address"}],
        "name": "revokeEmergencyUnlock",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "lp", "type": "address"}],
        "name": "emergencyUnlocked",
        "outputs": [{"name": "", "type": "bool"}],
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
    {
        "inputs": [{"name": "amount", "type": "uint256"}],
        "name": "withdraw",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

MARKET_ABI: list[dict[str, Any]] = [
    {
        "inputs": [],
        "name": "phase",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "nextTicketId",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "ticketSize",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "commitDeadline",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "winningOutcomeId",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "i", "type": "uint256"}],
        "name": "batchRoots",
        "outputs": [{"name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "i", "type": "uint256"}],
        "name": "batchCounts",
        "outputs": [{"name": "", "type": "uint16"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "ticketId", "type": "uint256"}],
        "name": "commitmentAt",
        "outputs": [{"name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "outcomeId", "type": "uint256"}],
        "name": "postResult",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "proof", "type": "bytes"},
            {"name": "publicSignals", "type": "uint256[10]"},
        ],
        "name": "verifyAndSettle",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "proofs", "type": "bytes[]"},
            {"name": "publicSignals", "type": "uint256[10][]"},
            {"name": "batchIndexes", "type": "uint16[]"},
        ],
        "name": "verifyAndSettleBatched",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "user", "type": "address"},
            {"name": "ticketId", "type": "uint256"},
            {"name": "outcomeId", "type": "uint256"},
            {"name": "amount", "type": "uint256"},
            {"name": "payout", "type": "uint256"},
            {"name": "salt", "type": "bytes32"},
            {"name": "merkleProof", "type": "bytes32[]"},
        ],
        "name": "claim",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "ticketId", "type": "uint256"}],
        "name": "claimedTickets",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "batchIndex", "type": "uint16"}],
        "name": "batchProofVerified",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "marketId",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "maxCommitments",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "oracle",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "resultPosted",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "rakeBps",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalEscrow",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "roots", "type": "bytes32[]"},
            {"name": "counts", "type": "uint16[]"},
            {"name": "relayerSig", "type": "bytes"},
        ],
        "name": "lockBatches",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

# ---------------------------------------------------------------------------
# Web3 setup
# ---------------------------------------------------------------------------


def build_web3(rpc_url: str = RPC_URL) -> Web3:
    web3 = Web3(HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
    if _poa_middleware is not None:
        web3.middleware_onion.inject(_poa_middleware, layer=0)
    elif ExtraDataToPOAMiddleware is not None:
        web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if not web3.is_connected():
        raise ConnectionError(f"Failed to connect to RPC at {rpc_url}")
    return web3


def contract(web3: Web3, address: str, abi: list[dict[str, Any]]) -> Contract:
    return web3.eth.contract(address=web3.to_checksum_address(address), abi=abi)


def send_tx(web3: Web3, private_key: str, tx_func, *, label: str = "tx") -> dict:
    """Build, sign, send and wait for a transaction. Returns the receipt dict."""
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
    log.info("[%s] Explorer: %s/tx/0x%s", label, EXPLORER_URL, tx_hex)

    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    status = receipt.get("status", -1)
    gas_used = receipt.get("gasUsed", 0)
    block = receipt.get("blockNumber", 0)
    log.info("[%s] Mined: status=%s block=%s gas=%s", label, status, block, gas_used)

    if status != 1:
        raise RuntimeError(f"[{label}] Transaction reverted! tx=0x{tx_hex}")

    return dict(receipt)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def api_get(path: str, *, headers: dict | None = None) -> dict:
    """GET request to the backend API."""
    url = f"{API_URL}{path}"
    h = {"X-Internal-Secret": INTERNAL_SECRET}
    if headers:
        h.update(headers)
    resp = httpx.get(url, headers=h, timeout=30)
    resp.raise_for_status()
    return resp.json()


def api_post(path: str, data: dict, *, headers: dict | None = None) -> dict:
    """POST request to the backend API."""
    url = f"{API_URL}{path}"
    h = {"Content-Type": "application/json", "X-Internal-Secret": INTERNAL_SECRET}
    if headers:
        h.update(headers)
    resp = httpx.post(url, json=data, headers=h, timeout=30)
    resp.raise_for_status()
    return resp.json()


def relayer_post(path: str, data: dict) -> dict:
    """POST request to the relayer."""
    url = f"{RELAYER_URL}{path}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {RELAYER_BEARER}",
    }
    resp = httpx.post(url, json=data, headers=headers, timeout=60)
    if resp.status_code >= 400:
        log.error("Relayer error %d: %s", resp.status_code, resp.text)
    resp.raise_for_status()
    return resp.json()


def prover_post(path: str, data: dict) -> dict:
    """POST request to the prover."""
    url = f"{PROVER_URL}{path}"
    headers = {
        "Content-Type": "application/json",
        "X-Prover-Secret": PROVER_SECRET,
    }
    resp = httpx.post(url, json=data, headers=headers, timeout=300)
    resp.raise_for_status()
    return resp.json()


def wait_for_relayer_job(job_id: str, *, timeout: int = 120) -> dict:
    """Poll relayer /status until the queued job completes."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = httpx.post(
            f"{RELAYER_URL}/status",
            json={"jobId": job_id},
            headers={"Authorization": f"Bearer {RELAYER_BEARER}", "Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        status = result.get("status", "unknown")
        if status in ("completed", "done", "mined", "succeeded"):
            log.info("Job %s completed: %s", job_id, result.get("txHash", ""))
            return result
        if status in ("failed", "dead", "deadletter"):
            raise RuntimeError(f"Relayer job {job_id} failed: {result}")
        time.sleep(2)
    raise TimeoutError(f"Relayer job {job_id} did not complete within {timeout}s")


# ---------------------------------------------------------------------------
# CommitAuth signing (mirrors trade.py:1839)
# ---------------------------------------------------------------------------


def sign_commit_auth(
    market_address: str,
    market_id: int,
    ticket_id: int,
    commitment: bytes,
    user_address: str,
    nonce: int,
    expiry: int,
    ticket_value_wei: int,
    chain_id: int = CHAIN_ID,
    signer_key: str = AUTH_SIGNER_KEY,
) -> str:
    """Sign a CommitAuth digest matching the on-chain verification in RevealMarket.commitWithAuthorization.

    The contract computes: keccak256(abi.encodePacked(
        address(this), marketId, ticketId, commitment, user, nonce, expiry, ticketValue, chainId
    )) then wraps with toEthSignedMessageMessage before ecrecover.
    """
    digest = Web3.solidity_keccak(
        ["address", "uint256", "uint256", "bytes32", "address", "uint256", "uint256", "uint256", "uint256"],
        [
            Web3.to_checksum_address(market_address),
            market_id,
            ticket_id,
            commitment,
            Web3.to_checksum_address(user_address),
            nonce,
            expiry,
            ticket_value_wei,
            chain_id,
        ],
    )
    signed = Account.sign_message(encode_defunct(hexstr=digest.hex()), signer_key)
    return "0x" + signed.signature.hex()


# ---------------------------------------------------------------------------
# State persistence between scripts
# ---------------------------------------------------------------------------


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    log.info("State saved to %s", STATE_FILE)


def load_state() -> dict:
    if not STATE_FILE.exists():
        raise FileNotFoundError(f"State file not found: {STATE_FILE}. Run earlier phases first.")
    return json.loads(STATE_FILE.read_text())


def update_state(**kwargs) -> dict:
    """Load existing state, update with kwargs, save back."""
    try:
        state = load_state()
    except FileNotFoundError:
        state = {}
    state.update(kwargs)
    save_state(state)
    return state


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def wei_to_zen(wei: int) -> str:
    return f"{Decimal(wei) / Decimal(10**18):.4f} ZEN"


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def phase_name(phase_int: int) -> str:
    names = {0: "Commit", 1: "Locked", 2: "Settled", 3: "Cancelled", 4: "Refunding"}
    return names.get(phase_int, f"Unknown({phase_int})")


def header(title: str):
    log.info("=" * 60)
    log.info("  %s", title)
    log.info("=" * 60)


def check(label: str, condition: bool, detail: str = ""):
    if condition:
        log.info("  PASS  %s %s", label, detail)
    else:
        log.error("  FAIL  %s %s", label, detail)
    return condition
