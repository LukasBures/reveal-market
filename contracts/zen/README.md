# Reveal Market – Zen Workspace

Foundry workspace for the Horizen appchain contracts that power fixed-size commit/reveal markets with Poseidon batch settlement.

## Components

- **MarketFactory** – EIP-1167 clone deployer for `RevealMarket`. Stores oracle, authorization signer, relayer escrow, verifier, circuit hash, rake, ticket size, commit deadline, max commitments, and protocol liability cap. Registers markets with ProtocolPool + RelayerEscrow; `syncFactoryHooks` sets the factory on both.
- **RelayerEscrow** – Holds user collateral, exposes `deposit/withdraw`, and forwards fixed-size tickets to markets via `commitOnBehalf` using backend-signed authorizations. `creditFromMarket` exists for escrow payouts (claims currently pay users directly).
- **ProtocolPool** – Protocol bankroll; enforces per-market liability caps, tops up deficits at settlement, and collects rake/surplus. Only factory-registered markets may draw.
- **RevealMarket** – Stores commitments, locks Poseidon batch roots, verifies Groth16 proofs, and pays claims. Supports refunds after commit deadline, per-market pauses, and deadline extensions (monotonic).
- **Verifier** – Groth16 verifier with stored circuit hash (field-reduced mod BN254).

Batch constants: `BATCH_SIZE = 256`, `MERKLE_DEPTH = 8` (Poseidon trees). Settlement uses `verifyAndSettleBatched` for multi-batch or `verifyAndSettle` when a single batch exists.

## Flow

1. Users deposit ZEN ERC20 into `RelayerEscrow` (gas paid separately).
2. Backend signs `CommitAuth` digest; relayer calls `commitOnBehalf` → `commitWithAuthorization` with fixed ticket value. Rake is skimmed to ProtocolPool at commit; commitments are stored.
3. After `commitDeadline`, oracle calls `lockBatches` with Poseidon roots + per-batch counts (optional relayer signature). Single-batch markets set `commitmentsRoot`; multi-batch zero it and rely on per-batch roots.
4. Oracle posts result and settles via `verifyAndSettleBatched` (or `verifyAndSettle` for single batch). Checks circuit hash, rake, totals, and protocol cap (`totalLiability <= totalEscrowNet + protocolCap`), draws from ProtocolPool as needed, and returns surplus.
5. Anyone calls `claim` with Poseidon Merkle proof for the ticket; payouts go directly to the user. After claim window, factory can sweep unclaimed amounts to ProtocolPool or RelayerEscrow.

## Digests & Hashes

- **Commit authorization**: `keccak256(abi.encodePacked(address(market), marketId, commitment, user, nonce, expiry, ticketValue, block.chainid))` signed by `authorizationSigner`. Nonces/expiries enforced; commit value must equal fixed ticket size.
- **Public signals** (10): `[merkleRoot, marketId, winningOutcomeId, totalEscrowNet, totalLiability, rakeBps, poolTotalYes, poolTotalNo, circuitHash, padding(0)]`.
- **Commitment leaf (Poseidon)**: `leaf = Poseidon(Poseidon(ticketId, outcomeId), Poseidon(amount, Poseidon(user, salt)))`, stored as `bytes32(uint256(leaf))`.

## Admin Controls

- Factory owner: update rake, authorization signer, oracle, relayer escrow, protocol cap, commit deadline (extend only), pauses (`setFactoryPaused`, `setCommitsPaused`, `setClaimsPaused`), enable refunds after commit deadline, sync rake to markets, rotate verifier/circuit hash for new markets.
- ProtocolPool/RelayerEscrow require factory hooks to be set (`syncFactoryHooks`) for new deployments or rotations.

## Commands

```bash
cd contracts/zen
forge fmt
forge build
forge test
./run_local.sh        # build + tests + gas snapshot check
./run_local.sh full   # add fuzz + coverage
```

Deployment helpers:

- `run_deploy.sh` – reads `.env` for RPC/chain id/deployer key/token/authorization signer/oracle/verifier/circuit hash/ticket size/caps/deadline; deploys ProtocolPool, RelayerEscrow, RevealMarket impl, Verifier, and MarketFactory.
- `scripts/create_market.sh` – create a market from env (`FACTORY_ADDRESS`, `VERIFIER_ADDRESS`, `CIRCUIT_HASH`, `TICKET_SIZE_WEI`, `MAX_COMMITMENTS`, `PROTOCOL_LIABILITY_CAP_WEI`, `COMMIT_DEADLINE` or `COMMIT_LEAD_SECONDS`, oracle/signer addresses). Prints JSON payload for audit.

## Network Defaults (Horizen testnet)

- `CHAIN_ID=2651420`
- `RPC_URL=https://horizen-testnet.rpc.caldera.xyz/http`
- Example `.env` entries for deploy/create scripts:
  - `PRIVATE_KEY=<deployer key>`
  - `ZEN_TOKEN_ADDRESS=<ERC20 collateral>`
  - `AUTHORIZATION_SIGNER=<backend signer>`
  - `ORACLE_ADDRESS=<oracle EOA>`
  - `SETTLEMENT_VK_JSON` or `SETTLEMENT_VK_PATH` (from prover artifacts)

## Operational Notes

- Keep circuit hash/verifier/`contracts/cache/settlement-vk.json` aligned with prover artifacts and backend config; mismatches cause settlement failure by design.
- Batching constants are fixed (256 tickets, depth 8); adjust backend/prover/relayer only if the circuit changes.
- `RelayerEscrow` must know `marketFactory`; call `syncFactoryHooks` after rotating factory or escrow.
- Market upgrades require deploying a new implementation + factory; existing markets stay on the old implementation.
