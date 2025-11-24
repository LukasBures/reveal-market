// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

import {MarketFactory} from "../src/MarketFactory.sol";
import {RevealMarket} from "../src/RevealMarket.sol";
import {RakeManager} from "../src/RakeManager.sol";
import {MockVerifier} from "./mocks/MockVerifier.sol";

contract AdminGuardsTest is Test {
    MarketFactory private factory;
    RakeManager private rakeManager;
    RevealMarket private implementation;
    MockVerifier private verifier;

    address payable private constant TREASURY = payable(address(0xBEEF));
    address private constant ORACLE = address(0xA11CE);
    address private guardian = address(0xCAFE);

    function setUp() public {
        implementation = new RevealMarket();
        rakeManager = new RakeManager(address(this), TREASURY, 100);
        verifier = new MockVerifier();
        factory = new MarketFactory(address(implementation), address(rakeManager), TREASURY, address(verifier));
        factory.setGuardian(guardian);
    }

    function testFactoryPauseGuarded() public {
        vm.prank(address(0xBAD));
        vm.expectRevert(MarketFactory.NotGuardianOrOwner.selector);
        factory.setGlobalCommitPaused(true);

        vm.prank(guardian);
        factory.setGlobalCommitPaused(true);
        assertTrue(factory.globalCommitPaused());
    }

    function testFactoryGuardianZeroRejects() public {
        vm.expectRevert(MarketFactory.ZeroAddress.selector);
        factory.setGuardian(address(0));
    }

    function testRakeManagerBounds() public {
        uint256 aboveMax = rakeManager.MAX_RAKE_BPS() + 1;

        vm.expectRevert(RakeManager.InvalidRakeBps.selector);
        rakeManager.setRakeBps(aboveMax);

        vm.expectRevert(RakeManager.InvalidRakeBps.selector);
        rakeManager.takeRake(address(0), 1 ether, aboveMax);
    }

    function testRakeManagerOwnershipRequired() public {
        vm.prank(address(0xBAD));
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, address(0xBAD)));
        rakeManager.setTreasury(TREASURY);
    }
}
