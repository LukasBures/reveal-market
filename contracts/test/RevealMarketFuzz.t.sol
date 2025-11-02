// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {RevealMarket} from "../src/RevealMarket.sol";
import {RakeManager} from "../src/RakeManager.sol";
import {Verifier} from "../src/Verifier.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

contract RevealMarketFuzzTest is Test {
    RevealMarket private market;
    RakeManager private rakeManager;
    Verifier private verifier;
    MockERC20 private collateralToken;

    address private constant ORACLE = address(0xF001);
    address payable private constant TREASURY = payable(address(0xF002));
    address private constant USER = address(0xF003);
    address private constant OTHER = address(0xF004);
    string private constant OUTCOME = "YES";
    bytes32 private constant LOSE_SALT = bytes32(uint256(999));

    function setUp() public {
        market = new RevealMarket();
        rakeManager = new RakeManager(address(this), TREASURY, 50);
        verifier = new Verifier();
        collateralToken = new MockERC20("USDC", "USDC", 6);

        uint256 commitDeadline = block.timestamp + 2 days;
        uint256 revealDeadline = commitDeadline + 1 days;

        // initialize() now has 9 parameters (removed metadataURI)
        market.initialize(
            "FUZZ",
            commitDeadline,
            revealDeadline,
            ORACLE,
            address(verifier),
            address(rakeManager),
            address(TREASURY),
            address(collateralToken),
            address(this)
        );
    }

    function testFuzzCommitClaim(uint96 stakeRaw, bytes32 winnerSalt) public {
        uint256 stake = bound(uint256(stakeRaw), 1e6, 1_000_000_000e6);
        bytes32 salt = winnerSalt == bytes32(0) ? bytes32(uint256(1)) : winnerSalt;

        _commit(USER, salt, stake);
        _commit(OTHER, LOSE_SALT, stake);

        vm.warp(market.commitDeadline() + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(keccak256(bytes(OUTCOME)));

        uint256[4] memory pubSignals;
        pubSignals[0] = stake;
        market.verifyProof(new bytes(0), pubSignals);

        uint256 before = collateralToken.balanceOf(USER);
        vm.prank(USER);
        market.claim(0, OUTCOME, salt);
        uint256 afterBalance = collateralToken.balanceOf(USER);
        assertGt(afterBalance, before);
    }

    function _commit(address user, bytes32 salt, uint256 amount) internal {
        collateralToken.mint(user, amount);
        vm.prank(user);
        collateralToken.approve(address(market), amount);
        bytes32 ticketHash = keccak256(abi.encodePacked(user, keccak256(bytes(OUTCOME)), salt));
        vm.prank(user);
        market.commit(ticketHash, amount);
    }
}