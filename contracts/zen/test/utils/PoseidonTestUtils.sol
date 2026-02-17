// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {PoseidonT3} from "../../src/crypto/PoseidonT3.sol";

abstract contract PoseidonTestUtils {
    uint256 internal constant BATCH_SIZE = 256;
    uint256 internal constant MERKLE_DEPTH = 8;

    function _salt(string memory value) internal pure returns (bytes32) {
        return bytes32(keccak256(abi.encodePacked(value)));
    }

    function _poseidonLeaf(
        uint256 ticketId,
        uint256 outcomeId,
        uint256 amount,
        uint256 payout,
        bytes32 salt,
        address user
    ) internal pure returns (bytes32) {
        uint256 userSalt = PoseidonT3.poseidon([uint256(uint160(user)), uint256(salt)]);
        uint256 h1 = PoseidonT3.poseidon([ticketId, outcomeId]);
        uint256 h2 = PoseidonT3.poseidon([amount, payout]);
        uint256 h3 = PoseidonT3.poseidon([h2, userSalt]);
        uint256 leaf = PoseidonT3.poseidon([h1, h3]);
        return bytes32(leaf);
    }

    function _poseidonHashPair(bytes32 left, bytes32 right) internal pure returns (bytes32) {
        return bytes32(PoseidonT3.poseidon([uint256(left), uint256(right)]));
    }

    function _buildBatchRoot(bytes32[] memory leaves, uint256 count) internal pure returns (bytes32) {
        bytes32[] memory level = _buildPaddedLeaves(leaves, count);
        uint256 levelSize = BATCH_SIZE;
        for (uint256 depth = 0; depth < MERKLE_DEPTH; depth++) {
            uint256 nextSize = levelSize / 2;
            bytes32[] memory nextLevel = new bytes32[](nextSize);
            for (uint256 i = 0; i < nextSize; i++) {
                uint256 offset = i * 2;
                nextLevel[i] = _poseidonHashPair(level[offset], level[offset + 1]);
            }
            level = nextLevel;
            levelSize = nextSize;
        }
        return level[0];
    }

    function _buildMerkleProof(bytes32[] memory leaves, uint256 count, uint256 index)
        internal
        pure
        returns (bytes32[] memory)
    {
        bytes32[] memory proof = new bytes32[](MERKLE_DEPTH);
        bytes32[] memory level = _buildPaddedLeaves(leaves, count);
        uint256 levelSize = BATCH_SIZE;
        uint256 idx = index;
        for (uint256 depth = 0; depth < MERKLE_DEPTH; depth++) {
            uint256 siblingIndex = idx ^ 1;
            proof[depth] = level[siblingIndex];

            uint256 nextSize = levelSize / 2;
            bytes32[] memory nextLevel = new bytes32[](nextSize);
            for (uint256 i = 0; i < nextSize; i++) {
                uint256 offset = i * 2;
                nextLevel[i] = _poseidonHashPair(level[offset], level[offset + 1]);
            }
            level = nextLevel;
            levelSize = nextSize;
            idx = idx / 2;
        }
        return proof;
    }

    function _buildPaddedLeaves(bytes32[] memory leaves, uint256 count) internal pure returns (bytes32[] memory) {
        bytes32[] memory padded = new bytes32[](BATCH_SIZE);
        for (uint256 i = 0; i < count; i++) {
            padded[i] = leaves[i];
        }
        for (uint256 i = count; i < BATCH_SIZE; i++) {
            padded[i] = bytes32(0);
        }
        return padded;
    }
}
