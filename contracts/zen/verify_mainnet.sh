#!/usr/bin/env bash
# Verify all ZEN L3 (Horizen Mainnet, chain 26514) contracts on Blockscout.
# Run from contracts/zen/:  bash verify_mainnet.sh
set -euo pipefail

CHAIN_ID=26514
RPC_URL="https://horizen.calderachain.xyz/http"
VERIFIER="blockscout"
VERIFIER_URL="https://horizen.calderaexplorer.xyz/api?"

# ── Deployed addresses (from broadcast/Deploy.s.sol/26514/run-latest.json) ────
PROTOCOL_POOL="0x3c8fc2c4bbe255ed8a8a343239a5ec8c016686b8"
RELAYER_ESCROW="0x5613c11e960950434444ba0580d9998f8540cfed"
REVEAL_MARKET="0x8a536445622ad4cdccdf2b464b88f5bd037f0516"
VERIFIER_ADDR="0x568c9395073d8132692be68e8de0e859b7f05c33"
MARKET_FACTORY="0x3144b525ffbb99df298e9b5a589011cf423b54a3"

# ── Constructor arg values (from broadcast arguments) ──────────────────────────
OWNER="0x5f7dCda0c23014c9133990739657A6d1f716d1DE"
COLLATERAL="0x57da2D504bf8b83Ef304759d9f2648522D7a9280"

# Verifier constructor args (ABI-encoded, extracted from broadcast tx input).
# This encodes: alpha1, beta2, gamma2, delta2, ic[11], circuitHash, expectedInputs.
VERIFIER_ARGS="0x2d4d9aa7e302d9df41749d5507949d05dbea33fbb16c643b22f599a2be6df2e214bedd503c37ceb061d8ec60209fe345ce89830a19230301f076caff004d19260967032fcbf776d1afc985f88877f182d38480a653f2decaa9794cbc3bf3060c0e187847ad4c798374d0d6732bf501847dd68bc0e071241e0213bc7fc13db7ab304cfbd1e08a704a99f5e847d93f8c3caafddec46b7a0d379da69a4d112346a71739c1b1a457a8c7313123d24d2f9192f896b7c63eea05a9d57f06547ad0cec8198e9393920d483a7260bfb731fb5d25f1aa493335a9e71297e485b7aef312c21800deef121f1e76426a00665e5c4479674322d4f75edadd46debd5cd992f6ed090689d0585ff075ec9e99ad690c3395bc4b313370b38ef355acdadcd122975b12c85ea5db8c6deb4aab71808dcb408fe3d1e7690c43d37b4ce6cc0166fa7daa1bd3fa9f9c6a7e6c7f09cc1a1defed4a3a3eea44f254e9d575181a7a53d9b49b19edff516105cebcafaa0a49ea807dde4acc8fb39f531a3cb2d65ec8b0501834152615f6eb7ad5ada4283420aa5ebeada800fc56bfa1270ed1bc12eba8bb1dc2050a84aaaedd129842b20aeaf0f5d100dc0e8d04a0aaa5c048d3b8b0bfa56f0d0000000000000000000000000000000000000000000000000000000000000220181e1866c82c6c72f18cd61723f1f61cd0a02224250b988af5a3f32863f2b157000000000000000000000000000000000000000000000000000000000000000a000000000000000000000000000000000000000000000000000000000000000b2b1b7456ba2d1f4e2a63db18e3a885ec047a0803dcafa2e317a1ce8e8cfb367e29c1940e9682ae755bee90d324d05732392bdbe2c5b3bf87aa947bf7a4200bf403be59cda6ad66bafbc3ff3b54da2dfbf00b628460e02a2bb79402c0305606d10ba0b314f61ca6019d2fd91e6bbe4c4b25199f909f74aed91cee7eaa198ede492d5695911ba283fe07de19cbbf709ab8eb4c86822e6acb9c1b7f2952ffa82a442b0ee46ac897dd4b4bf10d5b142de2e693376fb0445cdc58e858d372609afe240295e56e8da38c961c03137d36de14fbad9714bb9b719021d0768f6896ecc2aa1cdbe6548543efb355c6b14162701509577f52f82dd8d732120c86ab27cbc76b2f9b4292c5355c1a3306e8499e450d07726f33a6414c536f772853224204b3a52278c0953a2e10770fc7fd7101f38e1f23a0a967b1bdb9e8fbd5983e83be4d012fe673ebd97ea43ac588342fa8539094ef56ffdda0ef794c7302d8e0a0c77dd3076b78f9b6f03d4a82c8e71d97b48875657251ff727500fe7e308ec8e7cd34c82d089a57945d62fec073a2d734fd812b421c0369f7de6253abe2ba3c5e10825308c5c5d76b5ec86cf70d8cb3403be3b8312373393342c2fea7f32e038331f83d2befae641afaed9f79590dccf20ef71d81b241fe0dbfaa7c5e91128bbfd328972073c467fe0f67155c8beda3b4ab5e5c9339cf63319350866c56b7b53c19fe0001e5f1d9cfb45155cff1f5069d259a70152f5fdc4ab6d5c34602db48ecc339e9033c106d21cf9974d03c66ded69f2fa3b695437174a599ca9a64f7c8a49af74a1399849310bf60bf973bc3ce3cc7ccc964d7da8f97535af3b63d91f0a070af4d116748b63393affe4f16c65ca6c5a4dd2fbc63bd401cc089872681170916603a25a9afb151b3f93c734b34d65c9d02789db4c9d0f4b206175f62c11ead2633f0122e645bd6bd40d19fc7453c37e29fb3f08ed9220c90ab1f4ec70c1023760550"

COMMON_FLAGS=(
  --chain-id "$CHAIN_ID"
  --rpc-url "$RPC_URL"
  --verifier "$VERIFIER"
  --verifier-url "$VERIFIER_URL"
  --compiler-version "0.8.33"
  --via-ir
  --optimizer-runs 200
  --watch
)

echo "════════════════════════════════════════════════════════"
echo " Verifying ZEN L3 contracts on Horizen Mainnet (26514)"
echo "════════════════════════════════════════════════════════"

echo ""
echo "── 1/5  ProtocolPool ──────────────────────────────────"
forge verify-contract \
  "$PROTOCOL_POOL" \
  src/ProtocolPool.sol:ProtocolPool \
  --constructor-args "$(cast abi-encode 'constructor(address,address)' "$OWNER" "$COLLATERAL")" \
  "${COMMON_FLAGS[@]}"

echo ""
echo "── 2/5  RelayerEscrow ─────────────────────────────────"
forge verify-contract \
  "$RELAYER_ESCROW" \
  src/RelayerEscrow.sol:RelayerEscrow \
  --constructor-args "$(cast abi-encode 'constructor(address,address)' "$OWNER" "$COLLATERAL")" \
  "${COMMON_FLAGS[@]}"

echo ""
echo "── 3/5  RevealMarket (implementation) ─────────────────"
forge verify-contract \
  "$REVEAL_MARKET" \
  src/RevealMarket.sol:RevealMarket \
  "${COMMON_FLAGS[@]}"

echo ""
echo "── 4/5  Verifier ──────────────────────────────────────"
forge verify-contract \
  "$VERIFIER_ADDR" \
  src/Verifier.sol:Verifier \
  --constructor-args "$VERIFIER_ARGS" \
  "${COMMON_FLAGS[@]}"

echo ""
echo "── 5/5  MarketFactory ─────────────────────────────────"
forge verify-contract \
  "$MARKET_FACTORY" \
  src/MarketFactory.sol:MarketFactory \
  --constructor-args "$(cast abi-encode 'constructor(address,address,address,address,address)' \
    "$REVEAL_MARKET" "$PROTOCOL_POOL" "$RELAYER_ESCROW" "$COLLATERAL" "$OWNER")" \
  "${COMMON_FLAGS[@]}"

echo ""
echo "════════════════════════════════════════════════════════"
echo " Done."
echo "════════════════════════════════════════════════════════"
