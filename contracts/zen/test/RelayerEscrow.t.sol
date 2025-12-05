// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {RelayerEscrow} from "../src/RelayerEscrow.sol";
import {IRevealMarket} from "../src/interfaces/IRevealMarket.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

contract RelayerEscrowTest is Test {
    RelayerEscrow private escrow;
    MockERC20 private token;
    address private owner = makeAddr("relayer");
    address private user = makeAddr("user");

    function setUp() external {
        token = new MockERC20();
        escrow = new RelayerEscrow(owner, IERC20(address(token)));
    }

    function testDepositAndWithdraw() external {
        token.mint(user, 2 ether);
        vm.prank(user);
        token.approve(address(escrow), 2 ether);
        vm.prank(user);
        escrow.deposit(2 ether);
        assertEq(escrow.balances(user), 2 ether);

        vm.prank(user);
        escrow.withdraw(1 ether);
        assertEq(escrow.balances(user), 1 ether);
    }

    function testCommitFailsForUnknownMarket() external {
        IRevealMarket.CommitAuth memory auth =
            IRevealMarket.CommitAuth({commitment: bytes32(uint256(1)), nonce: 1, expiry: block.timestamp + 1});

        token.mint(user, 1 ether);
        vm.prank(user);
        token.approve(address(escrow), 1 ether);
        vm.prank(user);
        escrow.deposit(1 ether);

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
