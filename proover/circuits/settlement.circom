pragma circom 2.1.5;

include "circomlib/circuits/comparators.circom";

// Minimal MVP circuit: ensure winningPool > 0 and winningPool <= totalPool,
// while propagating the public inputs expected by RevealMarket.

template SettlementCircuit() {
    signal input totalPool;
    signal input winningPool;
    signal input outcomeHash;
    signal input circuitVersion;
    signal input nonce;
    signal input marketAddress;

    signal output pubTotalPool;
    signal output pubWinningPool;
    signal output pubOutcomeHash;
    signal output pubCircuitVersion;
    signal output pubNonce;
    signal output pubMarketAddress;

    component leqCheck = LessThan(256);
    leqCheck.in[0] <== winningPool;
    leqCheck.in[1] <== totalPool + 1;
    leqCheck.out === 1;

    component gtZero = LessThan(32);
    gtZero.in[0] <== 0;
    gtZero.in[1] <== winningPool;
    gtZero.out === 1;

    pubTotalPool <== totalPool;
    pubWinningPool <== winningPool;
    pubOutcomeHash <== outcomeHash;
    pubCircuitVersion <== circuitVersion;
    pubNonce <== nonce;
    pubMarketAddress <== marketAddress;
}

component main = SettlementCircuit();
