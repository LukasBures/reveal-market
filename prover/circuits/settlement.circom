pragma circom 2.1.5;

include "circomlib/circuits/comparators.circom";
include "circomlib/circuits/poseidon.circom";

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

    signal input commitmentsCount;
    signal input ticketId[256];
    signal input outcomeId[256];
    signal input amount[256];
    signal input user[256];
    signal input salt[256];

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

    component rakeCheck = LessThan(32);
    rakeCheck.in[0] <== rakeBps;
    rakeCheck.in[1] <== 10001; // rakeBps <= 10000
    rakeCheck.out === 1;

    component winnerRange = LessThan(6);
    winnerRange.in[0] <== winningOutcomeId;
    winnerRange.in[1] <== 2; // only YES/NO for MVP
    winnerRange.out === 1;

    component countCheck = LessThan(9);
    countCheck.in[0] <== commitmentsCount;
    countCheck.in[1] <== 257; // commitmentsCount <= 256
    countCheck.out === 1;

    signal isActive[256];
    signal userSalt[256];
    signal h1[256];
    signal h2[256];
    signal rawLeaf[256];
    signal leaf[256];
    signal outcomeSum[256];

    component activeCheck[256];
    component userSaltHash[256];
    component h1Hash[256];
    component h2Hash[256];
    component leafHash[256];
    component isYes[256];
    component isNo[256];

    signal poolYesAccum[257];
    signal poolNoAccum[257];
    poolYesAccum[0] <== 0;
    poolNoAccum[0] <== 0;

    for (var i = 0; i < 256; i++) {
        activeCheck[i] = LessThan(9);
        activeCheck[i].in[0] <== i;
        activeCheck[i].in[1] <== commitmentsCount;
        isActive[i] <== activeCheck[i].out;

        // Force inactive rows to contribute zero.
        amount[i] * (1 - isActive[i]) === 0;

        userSaltHash[i] = Poseidon(2);
        userSaltHash[i].inputs[0] <== user[i];
        userSaltHash[i].inputs[1] <== salt[i];
        userSalt[i] <== userSaltHash[i].out;

        h1Hash[i] = Poseidon(2);
        h1Hash[i].inputs[0] <== ticketId[i];
        h1Hash[i].inputs[1] <== outcomeId[i];
        h1[i] <== h1Hash[i].out;

        h2Hash[i] = Poseidon(2);
        h2Hash[i].inputs[0] <== amount[i];
        h2Hash[i].inputs[1] <== userSalt[i];
        h2[i] <== h2Hash[i].out;

        leafHash[i] = Poseidon(2);
        leafHash[i].inputs[0] <== h1[i];
        leafHash[i].inputs[1] <== h2[i];
        rawLeaf[i] <== leafHash[i].out;

        leaf[i] <== rawLeaf[i] * isActive[i];

        isYes[i] = IsEqual();
        isYes[i].in[0] <== outcomeId[i];
        isYes[i].in[1] <== 0;
        isNo[i] = IsEqual();
        isNo[i].in[0] <== outcomeId[i];
        isNo[i].in[1] <== 1;

        outcomeSum[i] <== isYes[i].out + isNo[i].out;
        (outcomeSum[i] - 1) * isActive[i] === 0;
        poolYesAccum[i + 1] <== poolYesAccum[i] + amount[i] * isYes[i].out;
        poolNoAccum[i + 1] <== poolNoAccum[i] + amount[i] * isNo[i].out;
    }

    signal poolYesComputed;
    signal poolNoComputed;
    signal totalEscrowComputed;
    signal totalLiabilityComputed;

    poolYesComputed <== poolYesAccum[256];
    poolNoComputed <== poolNoAccum[256];
    totalEscrowComputed <== poolYesComputed + poolNoComputed;

    component winYes = IsEqual();
    winYes.in[0] <== winningOutcomeId;
    winYes.in[1] <== 0;
    component winNo = IsEqual();
    winNo.in[0] <== winningOutcomeId;
    winNo.in[1] <== 1;
    winYes.out + winNo.out === 1;

    totalLiabilityComputed <== poolYesComputed * winYes.out + poolNoComputed * winNo.out;

    // Fixed depth-8 Poseidon Merkle root over 256 leaves.
    signal tree[9][256];
    component merkleHash[8][128];

    for (var i = 0; i < 256; i++) {
        tree[0][i] <== leaf[i];
    }

    for (var depth = 0; depth < 8; depth++) {
        var width = 256 >> (depth + 1);
        for (var j = 0; j < width; j++) {
            merkleHash[depth][j] = Poseidon(2);
            merkleHash[depth][j].inputs[0] <== tree[depth][2 * j];
            merkleHash[depth][j].inputs[1] <== tree[depth][2 * j + 1];
            tree[depth + 1][j] <== merkleHash[depth][j].out;
        }
    }

    tree[8][0] === merkleRoot;
    poolTotalYes === poolYesComputed;
    poolTotalNo === poolNoComputed;
    totalEscrow === totalEscrowComputed;
    totalLiability === totalLiabilityComputed;

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
