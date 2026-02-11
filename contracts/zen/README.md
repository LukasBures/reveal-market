# Contracts (Zen)

Core RevealMarket contracts.

**Key contracts**
- `RevealMarket`, `MarketFactory`, `ProtocolPool`, `RelayerEscrow`, `Verifier`.

**Commands**
- `forge build`
- `forge test`
- `./run_local.sh` for gas snapshots and optional fuzz.

**Operations**
- Rotate verifier key: `forge script script/RotateVerifierKey.s.sol --rpc-url $RPC_URL --broadcast`
  Requires `DEPLOYER_KEY`, `VERIFIER_ADDRESS`, `SETTLEMENT_VK_JSON`.

**Chain ID safety**
- `run_deploy.sh`, `scripts/create_market.sh`, and `scripts/check_circuit_hash.sh` now validate the RPC chain id.
- Set `EXPECTED_CHAIN_ID` (or `CHAIN_ID`) to fail fast when the RPC points at the wrong network.
