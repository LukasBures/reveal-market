// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {MarketFactory} from "../src/MarketFactory.sol";
import {ProtocolPool} from "../src/ProtocolPool.sol";
import {RelayerEscrow} from "../src/RelayerEscrow.sol";
import {RevealMarket} from "../src/RevealMarket.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {MockVerifier} from "./mocks/MockVerifier.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

contract OwnershipFlowsTest is Test {
    address private factoryOwner = makeAddr("factoryOwner");
    address private newFactoryOwner = makeAddr("newFactoryOwner");
    address private relayerOwner = makeAddr("relayerOwner");
    address private newRelayerOwner = makeAddr("newRelayerOwner");
    address private poolOwner = makeAddr("poolOwner");
    address private newPoolOwner = makeAddr("newPoolOwner");

    MarketFactory private factory;
    ProtocolPool private pool;
    RelayerEscrow private relayer;
    RevealMarket private implementation;
    MockERC20 private token;
    MockVerifier private verifier;

    function setUp() external {
        token = new MockERC20();
        pool = new ProtocolPool(poolOwner, IERC20(address(token)));
        relayer = new RelayerEscrow(relayerOwner, IERC20(address(token)));
        implementation = new RevealMarket();
        verifier = new MockVerifier(keccak256("ownership"));
        factory = new MarketFactory(address(implementation), pool, relayer, address(token), factoryOwner);
    }

    function testFactoryOwnable2Step() external {
        vm.prank(factoryOwner);
        factory.transferOwnership(newFactoryOwner);
        vm.prank(newFactoryOwner);
        factory.acceptOwnership();
        assertEq(factory.owner(), newFactoryOwner);
    }

    function testRelayerOwnable2Step() external {
        vm.prank(relayerOwner);
        relayer.transferOwnership(newRelayerOwner);
        vm.prank(newRelayerOwner);
        relayer.acceptOwnership();
        assertEq(relayer.owner(), newRelayerOwner);
    }

    function testProtocolPoolOwnable2Step() external {
        vm.prank(poolOwner);
        pool.transferOwnership(newPoolOwner);
        vm.prank(newPoolOwner);
        pool.acceptOwnership();
        assertEq(pool.owner(), newPoolOwner);
    }
}
