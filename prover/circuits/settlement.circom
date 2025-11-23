pragma circom 2.1.5;

include "circomlib/circuits/comparators.circom";
include "circomlib/circuits/bitify.circom";

// Settlement circuit public outputs (order must match on-chain verifier/public signals):
// 0: merkleRoot
// 1: marketId
// 2: winningOutcomeId
// 3: totalEscrow
// 4: totalLiability
// 5: rakeBps
// 6: poolTotalYes
// 7: poolTotalNo
// 8: circuitHash
// 9: padding (must be zero; kept to enforce 10-signal length)
template SettlementCircuit() {
    signal input merkleRoot;
    signal input marketId;
    signal input winningOutcomeId;
    signal input totalEscrow;
    signal input totalLiability;
    signal input rakeBps;
    signal input poolTotalYes;
    signal input poolTotalNo;
    signal input circuitHash;
    signal input padding;

    signal output pubMerkleRoot;
    signal output pubMarketId;
    signal output pubWinningOutcomeId;
    signal output pubTotalEscrow;
    signal output pubTotalLiability;
    signal output pubRakeBps;
    signal output pubPoolTotalYes;
    signal output pubPoolTotalNo;
    signal output pubCircuitHash;
    signal output pubPadding;

    // Basic sanity constraints
    component rakeCheck = LessThan(32);
    rakeCheck.in[0] <== rakeBps;
    rakeCheck.in[1] <== 10001; // rakeBps <= 10000
    rakeCheck.out === 1;

    component winnerRange = LessThan(6);
    winnerRange.in[0] <== winningOutcomeId;
    winnerRange.in[1] <== 2; // only YES/NO for MVP
    winnerRange.out === 1;

    component poolSum = LessThan(252);
    poolSum.in[0] <== poolTotalYes + poolTotalNo;
    poolSum.in[1] <== totalEscrow + 1;
    poolSum.out === 1;

    component liabilityCheck = LessThan(252);
    liabilityCheck.in[0] <== totalLiability;
    liabilityCheck.in[1] <== totalEscrow + 1;
    liabilityCheck.out === 1;

    // Keep the 10th public signal slot fixed at zero so the verifier enforces length without extra semantics.
    padding === 0;

    pubMerkleRoot <== merkleRoot;
    pubMarketId <== marketId;
    pubWinningOutcomeId <== winningOutcomeId;
    pubTotalEscrow <== totalEscrow;
    pubTotalLiability <== totalLiability;
    pubRakeBps <== rakeBps;
    pubPoolTotalYes <== poolTotalYes;
    pubPoolTotalNo <== poolTotalNo;
    pubCircuitHash <== circuitHash;
    pubPadding <== padding;
}

component main = SettlementCircuit();
