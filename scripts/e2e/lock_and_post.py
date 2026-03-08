#!/usr/bin/env python3
"""Manual lockBatches + postResult for E2E test market."""
import json, os, sys, importlib.util

# Load poseidon without polluting sys.path
_spec = importlib.util.spec_from_file_location("poseidon", "/app/shared/poseidon.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

from eth_abi import encode
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3, HTTPProvider

w3 = Web3(HTTPProvider("https://horizen-testnet.rpc.caldera.xyz/http"))
CHAIN_ID = 2651420

state = json.load(open("/tmp/prod_e2e_state.json"))
market_address = state["market_address"]
market_id = state["market_id"]
batch_root_bytes = bytes.fromhex(state["batch_root"][2:])
ticket_count = len(state["tickets"])

FACTORY = "0x07e13179E5231B3823f26ECBA2750834cBAfC9d3"
ORACLE_KEY = "REDACTED_SETTLEMENT_SIGNER_KEY"
RELAYER_KEY = os.environ.get("RELAYER_PRIVATE_KEY", "REDACTED_RELAYER_KEY")


def send(key, fn, label):
    acct = Account.from_key(key)
    nonce = w3.eth.get_transaction_count(acct.address, "pending")
    est = fn.estimate_gas({"from": acct.address})
    tx = fn.build_transaction({
        "from": acct.address, "nonce": nonce,
        "gas": int(est * 1.3), "gasPrice": w3.eth.gas_price, "chainId": CHAIN_ID,
    })
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    h = w3.eth.send_raw_transaction(raw)
    print(f"  [{label}] tx: 0x{h.hex()}")
    r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
    print(f"  [{label}] status={r['status']} block={r['blockNumber']} gas={r['gasUsed']}")
    assert r["status"] == 1, f"{label} REVERTED"
    return r


# Sign relayer digest
digest_data = encode(
    ["address", "address", "uint256", "bytes32[]", "uint16[]", "uint256"],
    [w3.to_checksum_address(market_address), w3.to_checksum_address(FACTORY),
     market_id, [batch_root_bytes], [ticket_count], CHAIN_ID],
)
relayer_sig = Account.sign_message(encode_defunct(Web3.keccak(digest_data)), RELAYER_KEY).signature
print(f"Relayer: {Account.from_key(RELAYER_KEY).address}")
print(f"Oracle:  {Account.from_key(ORACLE_KEY).address}")

# ABI
abi = [
    {"inputs": [{"name": "roots", "type": "bytes32[]"}, {"name": "counts", "type": "uint16[]"},
                {"name": "relayerSig", "type": "bytes"}],
     "name": "lockBatches", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [], "name": "phase", "outputs": [{"name": "", "type": "uint8"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "outcomeId", "type": "uint256"}], "name": "postResult",
     "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [], "name": "resultPosted", "outputs": [{"name": "", "type": "bool"}],
     "stateMutability": "view", "type": "function"},
]
mc = w3.eth.contract(address=w3.to_checksum_address(market_address), abi=abi)

phase = mc.functions.phase().call()
print(f"Phase: {phase}")

if phase == 0:
    print("\n=== lockBatches ===")
    send(ORACLE_KEY, mc.functions.lockBatches([batch_root_bytes], [ticket_count], relayer_sig), "lockBatches")
    print(f"Phase after lock: {mc.functions.phase().call()}")

phase = mc.functions.phase().call()
if phase == 1 and not mc.functions.resultPosted().call():
    print("\n=== postResult (YES=0) ===")
    send(ORACLE_KEY, mc.functions.postResult(0), "postResult")
    print(f"resultPosted: {mc.functions.resultPosted().call()}")

print(f"\nFinal phase: {mc.functions.phase().call()}")
print(f"Result posted: {mc.functions.resultPosted().call()}")
print("Done! Worker should now handle proof generation + settlement.")
