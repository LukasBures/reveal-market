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
