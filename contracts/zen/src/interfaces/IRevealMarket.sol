// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IRevealMarket {
    enum Phase {
        Commit,
        Locked,
        Settled,
        Finished
    }

    struct CommitAuth {
        bytes32 commitment;
        uint256 nonce;
        uint256 expiry;
    }

    function commitWithAuthorization(CommitAuth calldata auth, bytes calldata signature) external payable;

    function ticketSize() external view returns (uint256);

    function commitDeadline() external view returns (uint256);

    function phase() external view returns (Phase);

    function authorizationSigner() external view returns (address);

    function marketId() external view returns (uint256);
}
