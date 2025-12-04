# Reveal Market – Zen Contracts

Minimal, privacy-preserving on-chain stack for fixed-size commit/reveal markets with a trusted relayer and protocol-capped liability.

## Components
- `RelayerEscrow`: holds all user funds, exposes `deposit/withdraw`, and forwards fixed-size tickets to markets via `commitOnBehalf` using backend-signed auth. Markets return winnings via `creditFromMarket`.
- `ProtocolPool`: protocol bankroll that enforces per-market liability caps and collects rake/surplus. Only markets registered by the factory may draw.
- `MarketFactory`: owner-only EIP-1167 clone deployer for `RevealMarket`, wiring oracle, verifier, circuit hash, deadlines, fixed ticket size, max commitments, authorization signer, and protocol liability cap. Registers markets with escrow/pool; `syncFactoryHooks` sets itself on both. Rake is global (default 2%) and can be updated/synced to all markets.
- `RevealMarket`: per-event contract storing sealed commitments and minimal settlement state. Relayer-only commits, rake skimmed upfront to `ProtocolPool`, oracle-driven lock/result, Groth16 proof (`verifyAndSettle`) enforcing solvency + circuit hash, relayer-routed `claim`, and final surplus push to `ProtocolPool`.
- `Verifier`: configurable Groth16 verifier (10 public signals) with circuit hash.

## Flow
1) Users `deposit` into `RelayerEscrow` (native token, ZEN on Horizen testnet).
2) Backend issues `CommitAuth` signature; relayer calls `commitOnBehalf` → `market.commitWithAuthorization` with fixed ticket value (choose denominations like `0.01 ether` or `0.1 ether` per market); per-commit rake is forwarded immediately to `ProtocolPool`, net ticket value stays in-market, only commitments are stored.
3) After `commitDeadline`, oracle `lock()` (sets Merkle root) then `postResult`.
4) Oracle calls `verifyAndSettle(proof, pubSignals)`; market enforces `totalLiability <= totalEscrow + protocolCap`, draws from `ProtocolPool` if needed, asserts proof rakeBps matches current config (rake already collected), pushes any surplus to the pool, moves to `Settled`.
5) Relayer reveals winners via `claim(...)` with Merkle proof; payouts route to escrow, losers stay hidden. Once all liability claimed, market finishes and sends leftover to `ProtocolPool`.

## Admin Controls
- Factory owner rotates `authorizationSigner`, `oracle`, or `relayerEscrow` on existing markets; new relayers must set `marketFactory` before rotation so hooks succeed.
- Per-market `protocolLiabilityCap` is adjustable until settlement; global rake is mutable and can be pushed to markets.
- Commit/reveal deadlines can only be extended (never shortened) while in the matching phase.
- Pauses: `pauseFactory` stops new markets; `setCommitsPaused`/`setClaimsPaused` freeze activity per-market in emergencies.

## Public Signal Order (10)
`[merkleRoot, marketId, winningOutcomeId, totalEscrow, totalLiability, rakeBps, poolTotalYes, poolTotalNo, circuitHash, padding(0)]`

## Commit Authorization Digest
`keccak256(abi.encode(address(market), marketId, commitment, nonce, expiry))` → `eth_sign` by `authorizationSigner`.

## Build & Test
```bash
cd contracts/zen
forge fmt
forge test
```

## Deploy Notes
- Deploy `ProtocolPool`, `RelayerEscrow`, `RevealMarket` implementation, `Verifier` (with regenerated vk), then `MarketFactory`.
- Call `syncFactoryHooks()` so pool/escrow accept factory registrations.
- Use `MarketFactory.createMarket` with desired parameters; fixed ticket size + max commitments enforce anonymity set sizing.
