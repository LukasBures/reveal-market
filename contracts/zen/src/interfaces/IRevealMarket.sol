// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IRevealMarket {
    enum Phase {
        Commit,
        Locked,
        Settled
    }

    struct CommitAuth {
        bytes32 commitment;
        address user;
        uint256 nonce;
        uint256 expiry;
        uint256 ticketValue;
    }

    function commitWithAuthorization(CommitAuth calldata auth, bytes calldata signature) external payable;

    function ticketSize() external view returns (uint256);

    function commitDeadline() external view returns (uint256);

    function phase() external view returns (Phase);

    function authorizationSigner() external view returns (address);

    function marketId() external view returns (uint256);

    function nextTicketId() external view returns (uint256);

    function marketState()
        external
        view
        returns (bytes32 commitmentsRoot_, uint256 nextTicketId_, Phase phase_, uint256 commitDeadline_, uint256 winningOutcomeId_);
}
