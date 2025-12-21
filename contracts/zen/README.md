# Reveal Market – Zen Contracts

Minimal, privacy-preserving on-chain stack for fixed-size commit/reveal markets with a trusted relayer and protocol-capped liability.

## Components
- `RelayerEscrow`: holds user funds, exposes `deposit/withdraw`, and forwards fixed-size tickets to markets via `commitOnBehalf` using backend-signed auth. `creditFromMarket` exists for escrow-style payouts but `RevealMarket` currently pays users directly.
- `ProtocolPool`: protocol bankroll that enforces per-market liability caps and collects rake/surplus. Only markets registered by the factory may draw.
- `MarketFactory`: owner-only EIP-1167 clone deployer for `RevealMarket`, wiring oracle, verifier, circuit hash, deadlines, fixed ticket size, max commitments, authorization signer, and protocol liability cap. Registers markets with escrow/pool; `syncFactoryHooks` sets itself on both. Rake is global (default 2%) and can be updated/synced to all markets.
- `RevealMarket`: per-event contract storing sealed commitments and minimal settlement state. Relayer-only commits, rake skimmed upfront to `ProtocolPool`, oracle-driven lock/result, Groth16 proof (`verifyAndSettle`) enforcing solvency + circuit hash, open `claim` that pays ERC20 directly to the user address, and surplus push to `ProtocolPool` at settlement (no post-claim sweep yet).
- `Verifier`: configurable Groth16 verifier (10 public signals) with circuit hash.

## Flow
1) Users `deposit` ZEN ERC20 into `RelayerEscrow` (all collateral stays in-token; native gas still pays fees).
2) Backend issues `CommitAuth` signature; relayer calls `commitOnBehalf` → `market.commitWithAuthorization` with fixed ticket value (choose denominations like `0.1 ZEN` or `1 ZEN` per market); per-commit rake is forwarded immediately to `ProtocolPool`, net ticket value stays in-market, only commitments are stored.
3) After `commitDeadline`, oracle `lock()` (sets Merkle root) then `postResult`.
4) Oracle calls `verifyAndSettle(proof, pubSignals)`; market enforces `totalLiability <= totalEscrow(net) + protocolCap`, draws from `ProtocolPool` if needed, asserts proof `rakeBps` matches current config (rake already collected), pushes any surplus to the pool, moves to `Settled`.
5) Anyone (typically the relayer) calls `claim(...)` with Merkle proof; payouts transfer directly to the user address. Unclaimed payouts remain in the market until a sweep mechanism is added.

### Current state (what’s implemented)
- Fixed ticket value per market (constant in storage) with per-market `maxCommitments` to size the anonymity set and cap liability.
- Rake skimmed at commit time and tracked via pool events; settlement asserts proof rake matches current config so mismatched circuits fail.
- Commit deadlines enforce monotonic extensions only; `setCommitsPaused`/`setClaimsPaused` allow emergency halts without killing markets.
- Escape hatch: relayer or factory owner can `enableRefunds` after the commit deadline to cancel settlement and refund net tickets.
- Authorization signer enforced on every commit; digest binds market, id, commitment, user, nonce, expiry, ticket value, chain id. Nonces and expiries prevent replay.
- ProtocolPool tracks per-market draws and global balance; `ProtocolPool.draw` reverts on cap breach. Surplus flows back after settlement.
- Circuit hash stored in factory and market; settlement checks proof hash to prevent mismatched circuits.
- Verifier is configurable; tests assert correct calldata layout from prover and circuit hash alignment.
- Events emitted for every admin mutation (rake change, signer/oracle/relayer/escrow rotation, cap updates) to feed backend mirroring.

## Admin Controls
- Factory owner rotates `authorizationSigner`, `oracle`, or `relayerEscrow` on existing markets; new relayers must set `marketFactory` before rotation so hooks succeed.
- Per-market `protocolLiabilityCap` is adjustable until settlement; global rake is mutable and can be pushed to markets.
- Commit deadlines can only be extended (never shortened) while in the commit phase.
- Pauses: `pauseFactory` stops new markets; `setCommitsPaused`/`setClaimsPaused` freeze activity per-market in emergencies.

## Public Signal Order (10)
`[merkleRoot, marketId, winningOutcomeId, totalEscrowNet, totalLiability, rakeBps, poolTotalYes, poolTotalNo, circuitHash, padding(0)]`

## Commitment Leaf
`keccak256(ticketId, outcomeId, amount, keccak256(user, salt))` — user is bound to the leaf via a salted hash to preserve privacy while preventing redirection at claim time.

## Commit Authorization Digest
`keccak256(abi.encodePacked(address(market), marketId, commitment, user, nonce, expiry, ticketValue, block.chainid))` → `eth_sign` by `authorizationSigner`.

## Build & Test
```bash
cd contracts/zen
forge fmt
forge test
```

Tests cover authorization replay protection, deadline invariants, rake skim/draw accounting, protocol cap enforcement, surplus handling, pausing, oracle-only settle, claim proofs, and circuit hash validation. Gas snapshots run via `./run_local.sh full`.

## Deploy Notes
- Deploy `ProtocolPool`, `RelayerEscrow`, `RevealMarket` implementation, `Verifier` (with regenerated vk), then `MarketFactory`.
- Call `syncFactoryHooks()` so pool/escrow accept factory registrations (or set the factory directly on both).
- `run_deploy.sh` deploys infrastructure only; create markets separately via `MarketFactory.createMarket` (script or `cast send`).

### Environment (.env) needed for `run_deploy.sh` (Horizen testnet)
Create `contracts/zen/.env` (or export in your shell) with:
- `RPC_URL=https://horizen-testnet.rpc.caldera.xyz/http`
- `CHAIN_ID=2651420`
- `PRIVATE_KEY=<deployer key>` (e.g., `0x....77`)
- `ZEN_TOKEN_ADDRESS=<ZEN ERC20>` (e.g., `0x48e96bA58969f09e86B8B22AfEd12d3aF3367795`)
- `RELAYER_ADDRESS=<relayer EOA>` (e.g., `0xdAdEbecf077cdA5f86F60a91f76B238F675204f9`)
- `AUTHORIZATION_SIGNER=<authorization signer address>` (the backend holds the private key)
- `ORACLE_ADDRESS=<oracle EOA>` (e.g., `0x0F3d0f9274fA6AAEEbc493EdD44d2979BD75F369`)
- `CIRCUIT_HASH=<expected proof circuit hash>`
- `PROTOCOL_LIABILITY_CAP_WEI`
- `TICKET_SIZE_WEI`
- `MAX_COMMITMENTS`
- `RAKE_BPS`
- Verifier inputs: set `SETTLEMENT_VK_JSON` (raw JSON string) or `SETTLEMENT_VK_PATH` (file path, e.g., `contracts/zen/cache/settlement-vk.json`); set `USE_STUB_VERIFIER=1` only for local dev.

After deployment, note the new `RelayerEscrow` address and update `.env.local` / `.env.production`:
- `NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS`, `RM_RELAYER_ESCROW_ADDRESS`, `RELAYER_ESCROW_ADDRESS` → new escrow
- `NEXT_PUBLIC_ZEN_TOKEN_ADDRESS`, `ZEN_TOKEN_ADDRESS` → token address
- `RELAYER_PRIVATE_KEY` → relayer key (unchanged unless you rotate)

- CIRCUIT_HASH: The expected hash of the settlement circuit (Groth16) that markets verify in verifyAndSettle. Set this to the hash of your proving circuit so on-chain verification rejects proofs for a different circuit. Use the value produced when you generated the vk/proof artifacts.
- TICKET_SIZE_WEI: Fixed stake per commit (in wei). Every commitWithAuthorization must match this exact amount. Set to your chosen ticket size (e.g., 100000000000000000 for 0.1 ZEN).
- MAX_COMMITMENTS: Maximum number of commits (tickets) the market will accept. Controls the anonymity set and caps liability.
- RAKE_BPS: Rake in basis points (1 bp = 0.01%). 200 = 2% rake. Rake is skimmed on each commit and sent to ProtocolPool.
- PROTOCOL_LIABILITY_CAP_WEI: Per-market liability cap drawn from ProtocolPool to cover shortfall. Set to 0 to disable protocol top-up; otherwise set the cap in wei.

## Operational notes
- **Factory mirroring** – Backend worker should mirror `MarketCreated`, rake updates (`GlobalRakeUpdated`/`MarketRakeSynced`), `AuthorizationSignerUpdated`, and cap/escrow/oracle rotations to keep rake/circuit hash/signer aligned across services.
- **Verifier alignment** – Keep `contracts/zen/cache/settlement-vk.json` (and any mirrored cache), backend/prover circuit hash, and on-chain verifier in sync; mismatch forces settlement failure by design.
- **Relayer health** – `RelayerEscrow` requires `marketFactory` to be set; deployers must call `syncFactoryHooks` after deploying a new factory or rotating escrows/relayers.
- **Upgrades** – Market implementation is clone-based; to upgrade logic deploy a new implementation + factory and migrate addresses in backend envs. Old markets remain on the old implementation; adjust monitoring accordingly.
