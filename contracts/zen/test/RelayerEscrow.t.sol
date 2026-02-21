// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

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
        assertEq(escrow.balanceOf(user), 2 ether);

        vm.prank(user);
        escrow.withdraw(1 ether);
        assertEq(escrow.balances(user), 1 ether);
        assertEq(escrow.balanceOf(user), 1 ether);
    }

    function testCommitFailsForUnknownMarket() external {
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: bytes32(uint256(1)),
            ticketId: 0,
            user: user,
            nonce: 1,
            expiry: block.timestamp + 1,
            ticketValue: 1 ether
        });

        token.mint(user, 1 ether);
        vm.prank(user);
        token.approve(address(escrow), 1 ether);
        vm.prank(user);
        escrow.deposit(1 ether);

        vm.prank(owner);
        vm.expectRevert(RelayerEscrow.UnknownMarket.selector);
        escrow.commitOnBehalf(user, address(0xBEEF), auth, hex"");
    }

    function testCommitUserMismatchReverts() external {
        DummyMarket market = new DummyMarket(address(this), address(escrow), address(token));
        vm.prank(owner);
        escrow.setMarketFactory(address(this));
        escrow.registerMarket(address(market));

        address other = makeAddr("other");
        token.mint(user, 1 ether);
        vm.prank(user);
        token.approve(address(escrow), 1 ether);
        vm.prank(user);
        escrow.deposit(1 ether);

        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: bytes32(uint256(1)),
            ticketId: 0,
            user: other,
            nonce: 1,
            expiry: block.timestamp + 1,
            ticketValue: 1 ether
        });

        vm.prank(owner);
        vm.expectRevert(RelayerEscrow.UserMismatch.selector);
        escrow.commitOnBehalf(user, address(market), auth, hex"");
    }
}

contract DummyMarket is IRevealMarket {
    uint256 public ticket = 1 ether;
    address public override factory;
    address public override relayerEscrow;
    address public override collateralToken;

    constructor(address factory_, address relayerEscrow_, address collateralToken_) {
        factory = factory_;
        relayerEscrow = relayerEscrow_;
        collateralToken = collateralToken_;
    }

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

    function nextTicketId() external pure returns (uint256) {
        return 0;
    }

    function claimDeadline() external pure returns (uint256) {
        return 0;
    }

    function extendClaimDeadline(uint256) external pure {}

    function sweepUnclaimed(address) external pure {}

    function refundTicket(uint256) external pure {}

    function marketState()
        external
        pure
        returns (
            bytes32 commitmentsRoot_,
            uint256 nextTicketId_,
            Phase phase_,
            uint256 commitDeadline_,
            uint256 winningOutcomeId_
        )
    {
        return (bytes32(0), 0, Phase.Commit, 0, 0);
    }

    function batchRoots(uint256) external pure returns (bytes32) {
        return bytes32(0);
    }

    function batchCounts(uint256) external pure returns (uint16) {
        return 0;
    }

    function lockBatches(bytes32[] calldata, uint16[] calldata, bytes calldata) external {}

    function verifyAndSettleBatched(bytes[] calldata, uint256[10][] calldata, uint16[] calldata) external {}
}
