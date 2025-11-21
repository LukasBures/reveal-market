// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, StdInvariant} from "forge-std/Test.sol";

import {RevealMarket} from "../src/RevealMarket.sol";
import {MarketFactory} from "../src/MarketFactory.sol";
import {RakeManager} from "../src/RakeManager.sol";
import {MockVerifier} from "./mocks/MockVerifier.sol";

contract RevealMarketHandler is Test {
    RevealMarket public market;
    address public constant ORACLE = address(0xA11CE);
    address payable public constant TREASURY = payable(address(0xB0B));
    bytes32[] private tickets;

    constructor() {
        RakeManager rakeManager = new RakeManager(address(this), TREASURY, 100);
        MockVerifier verifier = new MockVerifier();
        MarketFactory factory = new MarketFactory(address(new RevealMarket()), address(rakeManager), TREASURY, address(verifier));

        MarketFactory.CreateMarketParams memory params;
        params.eventId = "INV";
        params.commitDeadline = block.timestamp + 3 days;
        params.revealDeadline = params.commitDeadline + 1 days;
        params.oracle = ORACLE;
        params.payoutMultiplier = 2e18;
        params.payoutCurve = RevealMarket.PayoutCurve.FixedOdds;
        params.maxMarketSize = 10 ether;
        address deployed = factory.createMarket(params);
        market = RevealMarket(payable(deployed));
        vm.deal(address(this), 10 ether);
        market.fundMarket{value: 5 ether}(5 ether);
    }

    receive() external payable {}

    function commit(bytes32 ticketHash, uint256 amount) external {
        amount = bound(amount, 0.01 ether, 1 ether);
        vm.deal(address(this), amount);
        market.commit{value: amount}(ticketHash, amount);
        tickets.push(ticketHash);
    }

    function lock() external {
        vm.warp(market.commitDeadline() + 1);
        if (tickets.length == 0) return;
        bytes32 root = tickets[0];
        for (uint256 i = 1; i < tickets.length; ++i) {
            root = keccak256(abi.encodePacked(root, tickets[i]));
        }
        market.lock(root, market.commitmentsCount());
    }

    function setPauses(bool commitPaused, bool claimPaused) external {
        market.setCommitPaused(commitPaused);
        market.setClaimPaused(claimPaused);
    }
}

contract RevealMarketInvariantTest is StdInvariant, Test {
    RevealMarketHandler private handler;

    function setUp() public {
        handler = new RevealMarketHandler();
        targetContract(address(handler));
    }

    function test_invariant_liabilityCovered() public view {
        RevealMarket m = handler.market();
        uint256 pool = address(m).balance;
        assertGe(pool + m.paidOut(), m.totalLiability(), "pool + paidOut must cover liability");
    }

    function test_invariant_pausesGuarded() public {
        RevealMarket m = handler.market();
        vm.prank(address(handler));
        m.setCommitPaused(true);
        vm.expectRevert(RevealMarket.CommitPaused.selector);
        // casting literal "x" to bytes32 is safe because it is a single byte with no truncation
        // forge-lint: disable-next-line(unsafe-typecast)
        m.commit{value: 0.1 ether}(bytes32("x"), 0.1 ether);
        vm.prank(address(handler));
        m.setCommitPaused(false);
    }
}
