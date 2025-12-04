# TODO – Zen Contracts

- Regenerate Groth16 artifacts for the updated settlement circuit and deploy a fresh verifier; update factory configs with the new `circuitHash`.
- Extend tests: fuzz Merkle inclusion/replay protection, protocol cap edges (draw failures), and multi-claim sequencing.
- Wire production-ready deploy scripts (env-driven market creation, protocol cap adjustments) to replace the minimal stub.
- Add monitoring hooks (events/metrics) for protocol pool draws and relayer credits if downstream expects them.
- Document off-chain signer lifecycle (rotation for `authorizationSigner` and relayer ownership changes) and add timelocks/pausers if required.
