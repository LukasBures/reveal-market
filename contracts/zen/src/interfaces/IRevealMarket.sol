// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

interface IRevealMarket {
    enum Phase {
        Commit,
        Locked,
        Settled,
        Cancelled
    }

    struct CommitAuth {
        bytes32 commitment;
        uint256 ticketId;
        address user;
        uint256 nonce;
        uint256 expiry;
        uint256 ticketValue;
    }

    function commitWithAuthorization(CommitAuth calldata auth, bytes calldata signature) external payable;

    function ticketSize() external view returns (uint256);

    function factory() external view returns (address);

    function relayerEscrow() external view returns (address);

    function collateralToken() external view returns (address);

    function commitDeadline() external view returns (uint256);

    function claimDeadline() external view returns (uint256);

    function phase() external view returns (Phase);

    function authorizationSigner() external view returns (address);

    function marketId() external view returns (uint256);

    function nextTicketId() external view returns (uint256);

    function marketState()
        external
        view
        returns (
            bytes32 commitmentsRoot_,
            uint256 nextTicketId_,
            Phase phase_,
            uint256 commitDeadline_,
            uint256 winningOutcomeId_
        );

    function batchRoots(uint256 index) external view returns (bytes32);

    function batchCounts(uint256 index) external view returns (uint16);

    function lockBatches(bytes32[] calldata roots, uint16[] calldata counts, bytes calldata relayerSig) external;

    function extendClaimDeadline(uint256 newDeadline) external;

    function sweepUnclaimed(address recipient) external;

    function refundTicket(uint256 ticketId) external;

    function verifyAndSettleBatched(
        bytes[] calldata proofs,
        uint256[10][] calldata publicSignals,
        uint16[] calldata batchIndexes
    ) external;
}
