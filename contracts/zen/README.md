# Contracts (Zen)

Core RevealMarket contracts for the Horizen Mainnet commit-and-reveal prediction market platform.

## Contracts

| Contract | Description |
|----------|-------------|
| `RevealMarket` | Single market instance: commit, lock, settle, claim |
| `MarketFactory` | Deploys deterministic `RevealMarket` clones; manages lifecycle and access control |
| `ProtocolPool` | Protocol-owned bankroll; caps per-market liability and holds LP deposits |
| `RelayerEscrow` | Holds user collateral balances; forwards commits to markets on behalf of users |
| `Verifier` | Configurable on-chain Groth16 verifier; verifying key is rotatable by owner |

Supporting files under `src/`:
- `crypto/PoseidonT3.sol` — in-circuit Poseidon hash (BN254)
- `utils/Pairing.sol` — BN254 pairing precompile wrapper
- `interfaces/` — `IRevealMarket`, `IProtocolPool`, `IRelayerEscrow`, `IVerifier`

---

## RevealMarket

Minimal commit/reveal market using fixed-size tickets and ZK-verified settlement.
Each market is an EIP-1167 minimal proxy clone initialized by `MarketFactory`.

### Market phases

```
Commit → Locked → Settled
                → Cancelled
```

- **Commit**: Users submit hidden position commitments before `commitDeadline`.
- **Locked**: Oracle calls `lockBatches` after the commit window closes; batch Merkle roots are finalized.
- **Settled**: ZK proof accepted via `verifyAndSettle` / `verifyAndSettleBatched`; winners can claim.
- **Cancelled**: Oracle or factory triggers refunds; users reclaim their tickets.

### Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `BATCH_SIZE` | `256` | Commitments per Merkle batch |
| `MERKLE_DEPTH` | `8` | Depth of the batch Merkle tree |
| `MAX_LOCK_BATCH_COUNT` | `64` | Maximum batches that can be locked in one call |
| `MAX_COMMITMENTS_LIMIT` | `16384` | `MAX_LOCK_BATCH_COUNT * BATCH_SIZE` |
| `MAX_COMMIT_DEADLINE_EXTENSION` | `30 days` | Maximum single extension of the commit deadline |
| `CLAIM_WINDOW_SECONDS` | `180 days` | Default claim window after settlement |
| `MAX_CLAIM_DEADLINE_EXTENSION` | `365 days` | Maximum total claim deadline extension |
| `SETTLEMENT_TIMEOUT_SECONDS` | `14 days` | Timeout after lock before refunds can be enabled |

### Key state variables

| Variable | Type | Description |
|----------|------|-------------|
| `phase` | `Phase` | Current market phase |
| `commitDeadline` | `uint256` | Timestamp after which commits are rejected |
| `ticketSize` | `uint256` | Fixed collateral amount per commitment |
| `maxCommitments` | `uint256` | Hard cap on total commitments |
| `rakeBps` | `uint256` | Protocol rake in basis points |
| `oracle` | `address` | Address authorized to lock and post results |
| `verifier` | `address` | Groth16 `Verifier` contract |
| `circuitHash` | `bytes32` | Expected circuit identifier |
| `lockedVerifierKeyHash` | `bytes32` | Verifying key hash snapshotted at lock time |
| `totalEscrow` | `uint256` | Sum of all net ticket deposits |
| `totalLiability` | `uint256` | Winning payout liability established at settlement |
| `rakeAmount` | `uint256` | Rake portion reserved from escrow |
| `winningOutcomeId` | `uint256` | Outcome posted by oracle |
| `batchRoots` | `bytes32[]` | Merkle roots for each locked batch |
| `claimDeadline` | `uint256` | Deadline for winners to claim |
| `refundDeadline` | `uint256` | Deadline for refunds in cancelled markets |

### Key functions

| Function | Caller | Description |
|----------|--------|-------------|
| `initialize(InitParams)` | Factory (once) | Initializes the clone; sets all market parameters |
| `commitWithAuthorization(auth, sig)` | RelayerEscrow | Records a Poseidon commitment for a user |
| `lockBatches(roots, counts, relayerSig)` | Oracle | Finalizes batch Merkle roots; transitions to Locked |
| `postResult(outcomeId)` | Oracle | Records winning outcome; required before settlement |
| `verifyAndSettle(proof, signals)` | Anyone | Verifies Groth16 proof for single-batch markets |
| `verifyAndSettleBatched(proofs, signals, indexes)` | Anyone | Verifies batch proofs for multi-batch markets |
| `claim(ticketId, leaf, proof, user)` | Relayer | Pays winner using Merkle proof; enforces claim deadline |
| `claimWithOracleAuthorization(...)` | Anyone | Claim via oracle-signed authorization (no Merkle proof) |
| `enableRefunds()` | Factory/anyone | Transitions cancelled markets to allow refunds |
| `refundTicket(ticketId)` | Anyone | Returns collateral for a ticket in a cancelled market |
| `sweepUnclaimed(recipient)` | Factory | Sweeps unclaimed payouts after claim deadline |
| `extendCommitDeadline(newDeadline)` | Factory | Extends commit window (once, max 30 days) |
| `extendClaimDeadline(newDeadline)` | Factory | Extends claim window (once, max 365 days total) |

### Public signals layout (`uint256[10]`)

| Index | Value |
|-------|-------|
| 0 | Batch Merkle root |
| 1 | `marketId` |
| 2 | `winningOutcomeId` |
| 3 | `totalEscrow` |
| 4 | `totalLiability` |
| 5 | `rakeBps` |
| 6–9 | Pool totals / padding (circuit-defined) |

---

## MarketFactory

Deploys deterministic `RevealMarket` clones (EIP-1167) and manages shared infrastructure.

### Key state variables

| Variable | Type | Description |
|----------|------|-------------|
| `IMPLEMENTATION` | `address` | Immutable `RevealMarket` implementation used for clones |
| `COLLATERAL_TOKEN` | `address` | Immutable ERC20 collateral token |
| `relayerEscrow` | `RelayerEscrow` | Active relayer escrow |
| `protocolPool` | `ProtocolPool` | Active protocol pool |
| `globalRakeBps` | `uint256` | Default rake applied to new markets (default: 200 = 2%) |
| `nextMarketId` | `uint256` | Auto-incrementing market ID |
| `isMarket` | `mapping(address => bool)` | Tracks deployed market addresses |
| `marketForId` | `mapping(uint256 => address)` | Market address by ID |
| `approvedVerifier` | `mapping(address => bool)` | Verifier attestation gate |
| `activeRelayers` | `address[]` | Relayers currently serving live markets |
| `MAX_RELAYER_PAUSE_BATCH` | `64` | Maximum relayers paused per batch call |

### Key functions

| Function | Description |
|----------|-------------|
| `createMarket(CreateMarketParams)` | Deploys a new clone and registers it with pool and escrow |
| `setVerifierApproval(verifier, approved)` | Attests or revokes a verifier; pins codehash and key hash |
| `clearVerifierPin(verifier)` | Clears pinned hashes after revocation to allow re-approval |
| `isVerifierCurrentlyApproved(verifier, hash)` | Runtime check used by markets during settlement |
| `setGlobalRakeBps(rakeBps)` | Updates rake applied to future markets |
| `syncMarketRake(market)` | Pushes current global rake to an existing market |
| `updateMarketRelayer(market, newRelayer)` | Rotates relayer for a market (only before any commits) |
| `updateMarketVerifier(market, verifier, hash)` | Rotates verifier for a market |
| `setRelayerCommitsPaused(paused)` | Emergency pause across all active relayers |
| `migrateMarketRelayerBalances(market, old, users)` | Moves user balances from old to new relayer |
| `sweepUnclaimed(market, recipient)` | Sweeps unclaimed payouts after claim deadline |
| `enableMarketRefunds(market)` | Enables refunds for a cancelled market |
| `predictMarketAddress(marketId)` | Returns the deterministic clone address |
| `getMarketParams(marketId)` | Returns all parameters for a deployed market |

---

## ProtocolPool

Protocol-owned bankroll that covers winning payouts when market escrow is insufficient.
External LPs can deposit collateral; LP losses reduce share value, LP profits are capped at principal.

### Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `LOCK_DURATION` | `30 days` | LP withdrawal lock period per deposit |

### Key state variables

| Variable | Type | Description |
|----------|------|-------------|
| `COLLATERAL_TOKEN` | `IERC20` | Immutable collateral token |
| `marketFactory` | `address` | Factory authorized to register markets (locked once set) |
| `liabilityCap` | `mapping(address => uint256)` | Maximum protocol exposure per market |
| `consumedLiability` | `mapping(address => uint256)` | Drawn liability per market |
| `reservedLiability` | `mapping(address => uint256)` | Reserved-but-not-drawn liability per market |
| `reservedTotal` | `uint256` | Sum of all active reservations |
| `totalShares` | `uint256` | Total outstanding LP shares (1:1 with deposited assets) |
| `capacity` / `capacityLimit` | `uint256` | Optional global risk budget |
| `drawsPaused` | `bool` | Emergency pause for all draws |

### Key functions

| Function | Caller | Description |
|----------|--------|-------------|
| `deposit(amount)` | Anyone | Deposit collateral; receive 1:1 LP shares locked for 30 days |
| `lpWithdraw(shares, minAssets)` | LP | Burn unlocked shares; subject to idle liquidity |
| `reserveLiability(market, amount)` | Market | Reserve capacity at lock time |
| `releaseLiabilityReservation(market)` | Market | Release unused reservation after settlement |
| `draw(market, amount)` | Market | Transfer coverage to market up to its cap |
| `withdraw(to, amount)` | Owner | Withdraw protocol surplus (above LP principal) |
| `forceReleaseLiability(market)` | Owner | Force-release orphaned reservation |
| `setCapacity(newCapacity)` | Owner | Set global risk budget (0 = disabled) |
| `setDrawsPaused(paused)` | Owner | Emergency pause for all market draws |
| `grantEmergencyUnlock(lp)` | Owner | Allow LP to withdraw before lock expires |
| `convertToAssets(shares)` | View | Share value (capped at 1:1; decreases under losses) |
| `protocolSurplus()` | View | Surplus above LP principal withdrawable by owner |
| `maxRedeemable(lp)` | View | Maximum shares LP can redeem now |

---

## RelayerEscrow

Holds user collateral balances and forwards fixed-size commits to markets on behalf of users.
Only the relayer (owner) can initiate commits; users deposit and withdraw freely.

### Key state variables

| Variable | Type | Description |
|----------|------|-------------|
| `COLLATERAL_TOKEN` | `IERC20` | Immutable collateral token |
| `balances` | `mapping(address => uint256)` | Per-user collateral balance |
| `allowedMarket` | `mapping(address => bool)` | Markets whitelisted by factory |
| `accountedCollateral` | `uint256` | Sum of all user balances |
| `marketFactory` | `address` | Factory authorized to register markets (locked once set) |
| `commitsPaused` | `bool` | Emergency pause for relayer commits |

### Key functions

| Function | Caller | Description |
|----------|--------|-------------|
| `deposit(amount)` | User | Transfer collateral into escrow balance |
| `depositFor(user, amount)` | Owner | Deposit on behalf of a user |
| `withdraw(amount)` | User | Withdraw from escrow balance to wallet |
| `withdrawTo(user, recipient, amount)` | Factory | Migration helper to move user balance |
| `commitOnBehalf(user, market, auth, sig)` | Owner (relayer) | Debit user balance and forward commit to market |
| `creditFromMarket(user, amount)` | Market | Receive payout from market into user balance |
| `creditMigrated(user, amount)` | Factory | Attribute pre-transferred collateral to user |
| `recoverExcessCollateral(recipient, amount)` | Owner | Recover collateral not assigned to any user |
| `setCommitsPaused(paused)` | Owner or Factory | Emergency pause for commits |
| `setMarketFactory(factory)` | Owner | Set factory (locked once set to a different address) |
| `registerMarket(market)` | Factory | Whitelist a deployed market |
| `unregisterMarket(market)` | Factory | Remove a market from the allowlist |

---

## Verifier

Configurable on-chain Groth16 verifier. Wraps BN254 pairing precompile logic; the verifying key is stored on-chain and can be rotated by the owner without redeploying markets.

### Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `EXPECTED_INPUTS` | `10` | Fixed number of public signals required by the settlement circuit |

### Key state variables

| Variable | Type | Description |
|----------|------|-------------|
| `circuitHash` | `bytes32` | Identifier for the circuit currently loaded |
| `verifyingKeyHash` | `bytes32` | `keccak256` of the full verifying key (α, β, γ, δ, IC, circuitHash, inputs) |
| `EXPECTED_INPUTS` | `uint256` | Immutable; set to 10 at construction |

### Key functions

| Function | Description |
|----------|-------------|
| `verifyProof(proofData, pubSignals)` | Runs Groth16 verification; returns `false` on invalid proof (does not revert) |
| `setVerifyingKey(alpha1, beta2, gamma2, delta2, icPoints, circuitHash_)` | Owner: rotate the verifying key |
| `expectedInputs()` | Returns `EXPECTED_INPUTS` (10) |
| `icLength()` | Returns length of the IC vector (`EXPECTED_INPUTS + 1`) |

Proof encoding: 256 bytes = `[A(G1), B(G2), C(G1)]` ABI-encoded as `(uint256[2], uint256[2][2], uint256[2])`.

---

## Commands

```bash
forge build
forge test

# Gas snapshots + optional extended fuzz
./run_local.sh

# Run test suite only
./run_tests.sh
```

## Forge scripts

| Script | Description |
|--------|-------------|
| `script/Deploy.s.sol` | Full deployment (Verifier → ProtocolPool → RelayerEscrow → MarketFactory) |
| `script/RotateVerifierKey.s.sol` | Rotate verifying key on a deployed Verifier |
| `script/ComputeVkHash.s.sol` | Compute and log the `verifyingKeyHash` for a key JSON |

```bash
# Rotate verifying key
forge script script/RotateVerifierKey.s.sol --rpc-url $RPC_URL --broadcast
# Requires: DEPLOYER_KEY, VERIFIER_ADDRESS, SETTLEMENT_VK_JSON
```

## Shell scripts

| Script | Description |
|--------|-------------|
| `scripts/create_market.sh` | Create a market via the factory |
| `scripts/check_circuit_hash.sh` | Validate the circuit hash on a deployed Verifier |
| `scripts/extend_claim_deadline.sh` | Extend claim deadline for a market |
| `scripts/sweep_unclaimed.sh` | Sweep unclaimed payouts after claim window |
| `scripts/generate_settlement_vk_json.py` | Generate verifying key JSON from a snarkjs export |

## Chain ID safety

`run_deploy.sh`, `scripts/create_market.sh`, and `scripts/check_circuit_hash.sh` validate the RPC chain ID before executing. Set `EXPECTED_CHAIN_ID` (or `CHAIN_ID`) to fail fast when the RPC points at the wrong network.

Default chain: Horizen Mainnet, chain ID `26514`, RPC `https://horizen.calderachain.xyz/http`.
