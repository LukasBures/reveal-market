# Reveal Relayer (Python)

Minimal HTTP relayer that submits `commitOnBehalf` and `claim` transactions to the Reveal Market contracts. Runs as a FastAPI service with Web3 + EOA signer.

## Requirements
- Python 3.12
- `uv` (package manager): `pip install uv` or download from https://github.com/astral-sh/uv
- RPC: Horizen Testnet `https://horizen-testnet.rpc.caldera.xyz/http` (default)

## Config (env vars)
- `RELAYER_PRIVATE_KEY`: hex EOA key used to sign txs.
- `RELAYER_ESCROW_ADDRESS`: deployed `RelayerEscrow` address.
- `RPC_URL`: JSON-RPC endpoint (e.g., Horizen testnet).
- `CHAIN_ID`: matching chain ID (e.g., `2651420`).
- `RELAYER_HOST`: bind host (e.g., `0.0.0.0`).
- `RELAYER_PORT`: bind port (e.g., `8088`).

## Install & Run (local)
```bash
cd relayer
uv sync
uv run uvicorn relayer.main:app --reload --host 0.0.0.0 --port 8088
```

## Docker
```bash
docker build -t reveal-relayer ./relayer
docker run --rm -p 8088:8088 \
  -e RELAYER_PRIVATE_KEY=0x... \
  -e RELAYER_ESCROW_ADDRESS=0x... \
  -e RPC_URL=https://horizen-testnet.rpc.caldera.xyz/http \
  reveal-relayer
```

## API
- `GET /healthz` — status + addresses.
- `POST /commit` — body: `user, market, commitment, nonce, expiry, signature, ticket_value_wei?`
- `POST /claim` — body: `market, user, ticket_id, outcome_id, amount, salt, merkle_proof[]`

Responses include `txHash` and `status`.

## Tests
```bash
cd relayer
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src uv run pytest
# or: make test
```

## Notes
- Service is stateless; wire it to your backend queue for commit/claim tasks.
- Gas funding: ensure the relayer EOA is funded on the target network.
- Contracts must match the deployed ABI (commit/claim paths). Update `abi.py` if needed.
