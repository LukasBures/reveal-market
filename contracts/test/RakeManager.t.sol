// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {RakeManager} from "../src/RakeManager.sol";

contract RakeManagerTest is Test {
    RakeManager private manager;
    address payable private treasury = payable(address(0xBEEF));

    function setUp() public {
        manager = new RakeManager(address(this), treasury, 100); // 1% default rake
    }

    function testInitialState() public view {
        assertEq(manager.treasury(), treasury);
        assertEq(manager.rakeBps(), 100);
    }

    function testSetRakeBps() public {
        manager.setRakeBps(50);
        assertEq(manager.rakeBps(), 50);
    }

    function testSetRakeBpsRevertsAboveMax() public {
        vm.expectRevert(RakeManager.InvalidRakeBps.selector);
        manager.setRakeBps(201);
    }

    function testSetTreasury() public {
        address payable newTreasury = payable(address(0xCAFE));
        manager.setTreasury(newTreasury);
        assertEq(manager.treasury(), newTreasury);
    }

    function testSetTreasuryRevertsOnZero() public {
        vm.expectRevert(RakeManager.InvalidTreasury.selector);
        manager.setTreasury(payable(address(0)));
    }

    function testTakeRakeReturnsNetAmount() public {
        uint256 expectedRake = (1 ether * manager.rakeBps()) / 10_000;
        vm.expectEmit(true, false, false, true);
        emit RakeManager.RakeTaken(address(0), 1 ether, expectedRake, treasury);
        uint256 net = manager.takeRake(address(0), 1 ether, 0);
        assertEq(net, 1 ether - expectedRake);
    }

    function testTakeRakeReturnsNetAmountForToken() public {
        uint256 amount = 1_000e6;
        uint256 overrideBps = 50;
        uint256 expectedRake = (amount * overrideBps) / 10_000;
        address token = address(0x1234);
        vm.expectEmit(true, false, false, true);
        emit RakeManager.RakeTaken(token, amount, expectedRake, treasury);
        uint256 net = manager.takeRake(token, amount, overrideBps);
        assertEq(net, amount - expectedRake);
    }

    function testTakeRakeRevertsAboveMaxOverride() public {
        uint256 maxBps = manager.maxRakeBps();
        vm.expectRevert(RakeManager.InvalidRakeBps.selector);
        manager.takeRake(address(0), 1 ether, maxBps + 1);
    }

    function testConstructorRevertsZeroTreasury() public {
        vm.expectRevert(RakeManager.InvalidTreasury.selector);
        new RakeManager(address(this), payable(address(0)), 0);
    }

    function testConstructorRevertsAboveMaxRake() public {
        vm.expectRevert(RakeManager.InvalidRakeBps.selector);
        new RakeManager(address(this), treasury, 400);
    }

    function testFuzzTakeRake(uint96 amountRaw, uint16 overrideRaw) public {
        uint256 amount = bound(uint256(amountRaw), 1, 1e30);
        uint256 overrideBps = bound(uint256(overrideRaw), 0, manager.MAX_RAKE_BPS());
        uint256 applied = overrideBps == 0 ? manager.rakeBps() : overrideBps;
        uint256 net = manager.takeRake(address(0), amount, overrideBps);
        uint256 rakeAmount = (amount * applied) / 10_000;
        assertEq(net + rakeAmount, amount);
    }
}
