// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {RelayerEscrow} from "../src/RelayerEscrow.sol";
import {IRevealMarket} from "../src/interfaces/IRevealMarket.sol";

contract RelayerEscrowTest is Test {
    RelayerEscrow private escrow;
    address private owner = makeAddr("relayer");
    address private user = makeAddr("user");

    function setUp() external {
        escrow = new RelayerEscrow(owner);
    }

    function testDepositAndWithdraw() external {
        vm.deal(user, 2 ether);
        vm.prank(user);
        escrow.deposit{value: 2 ether}();
        assertEq(escrow.balances(user), 2 ether);

        vm.prank(user);
        escrow.withdraw(1 ether);
        assertEq(escrow.balances(user), 1 ether);
    }

    function testCommitFailsForUnknownMarket() external {
        vm.deal(user, 1 ether);
        vm.prank(user);
        escrow.deposit{value: 1 ether}();

        IRevealMarket.CommitAuth memory auth =
            IRevealMarket.CommitAuth({commitment: bytes32(uint256(1)), nonce: 1, expiry: block.timestamp + 1});

        vm.prank(owner);
        vm.expectRevert(RelayerEscrow.UnknownMarket.selector);
        escrow.commitOnBehalf(user, address(0xBEEF), auth, hex"");
    }
}

contract DummyMarket is IRevealMarket {
    uint256 public ticket = 1 ether;

    function commitWithAuthorization(CommitAuth calldata, bytes calldata) external payable {}

    function ticketSize() external view returns (uint256) {
        return ticket;
    }

    function commitDeadline() external pure returns (uint256) {
        return 0;
    }

    function phase() external pure returns (Phase) {
        return Phase.Commit;
    }

    function authorizationSigner() external pure returns (address) {
        return address(0);
    }

    function marketId() external pure returns (uint256) {
        return 0;
    }
}
