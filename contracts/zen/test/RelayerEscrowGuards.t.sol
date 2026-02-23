// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Test} from "forge-std/Test.sol";

import {RelayerEscrow} from "../src/RelayerEscrow.sol";
import {IRevealMarket} from "../src/interfaces/IRevealMarket.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

contract RelayerEscrowGuardsTest is Test {
    RelayerEscrow private escrow;
    MockERC20 private token;
    address private owner = makeAddr("relayer");
    address private factory = makeAddr("factory");
    address private user = makeAddr("user");
    address private stranger = makeAddr("stranger");

    function setUp() external {
        token = new MockERC20();
        escrow = new RelayerEscrow(owner, IERC20(address(token)));
    }

    function testSetMarketFactoryOnlyOwner() external {
        vm.prank(stranger);
        vm.expectRevert();
        escrow.setMarketFactory(factory);

        vm.prank(owner);
        escrow.setMarketFactory(factory);
        assertEq(escrow.marketFactory(), factory);
    }

    function testSetMarketFactoryCannotRotate() external {
        vm.prank(owner);
        escrow.setMarketFactory(factory);

        vm.prank(owner);
        vm.expectRevert(RelayerEscrow.FactoryLocked.selector);
        escrow.setMarketFactory(makeAddr("nextFactory"));
    }

    function testSetMarketFactoryRejectsSpoofedOwnerContract() external {
        EscrowFactorySpoof spoof = new EscrowFactorySpoof(owner);
        vm.expectRevert();
        spoof.attack(escrow, factory);
        assertEq(escrow.marketFactory(), address(0), "factory unchanged");
    }

    function testRegisterMarketRequiresFactory() external {
        vm.prank(owner);
        escrow.setMarketFactory(factory);
        vm.prank(stranger);
        vm.expectRevert(RelayerEscrow.InvalidFactory.selector);
        escrow.registerMarket(makeAddr("market"));

        vm.prank(factory);
        vm.expectRevert(RelayerEscrow.InvalidMarket.selector);
        escrow.registerMarket(makeAddr("invalid"));

        DummyMarketGuard market = new DummyMarketGuard(factory, address(escrow), address(token));
        vm.prank(factory);
        escrow.registerMarket(address(market));
    }

    function testDepositForOnlyOwner() external {
        token.mint(owner, 1 ether);
        vm.prank(owner);
        token.approve(address(escrow), 1 ether);

        vm.prank(stranger);
        vm.expectRevert();
        escrow.depositFor(user, 1 ether);

        vm.prank(owner);
        escrow.depositFor(user, 1 ether);
        assertEq(escrow.balances(user), 1 ether);
    }

    function testCommitOnBehalfInsufficientBalance() external {
        DummyMarketGuard market = new DummyMarketGuard(address(this), address(escrow), address(token));
        vm.prank(owner);
        escrow.setMarketFactory(address(this));
        escrow.registerMarket(address(market));

        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: bytes32(uint256(1)),
            ticketId: 0,
            user: user,
            nonce: 1,
            expiry: block.timestamp + 1,
            ticketValue: 1 ether
        });

        vm.prank(owner);
        vm.expectRevert(RelayerEscrow.InsufficientBalance.selector);
        escrow.commitOnBehalf(user, address(market), auth, hex"");
    }

    function testCommitOnBehalfPaused() external {
        DummyMarketGuard market = new DummyMarketGuard(address(this), address(escrow), address(token));
        vm.prank(owner);
        escrow.setMarketFactory(address(this));
        escrow.registerMarket(address(market));

        token.mint(user, 1 ether);
        vm.prank(user);
        token.approve(address(escrow), 1 ether);
        vm.prank(user);
        escrow.deposit(1 ether);

        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: bytes32(uint256(1)),
            ticketId: 0,
            user: user,
            nonce: 1,
            expiry: block.timestamp + 1,
            ticketValue: 1 ether
        });

        vm.prank(owner);
        escrow.setCommitsPaused(true);

        vm.prank(owner);
        vm.expectRevert(RelayerEscrow.CommitsPaused.selector);
        escrow.commitOnBehalf(user, address(market), auth, hex"");
    }

    function testCommitOnBehalfRequiresUserAuthorization() external {
        DummyMarketGuard market = new DummyMarketGuard(address(this), address(escrow), address(token));
        vm.prank(owner);
        escrow.setMarketFactory(address(this));
        escrow.registerMarket(address(market));

        token.mint(user, 1 ether);
        vm.prank(user);
        token.approve(address(escrow), 1 ether);
        vm.prank(user);
        escrow.deposit(1 ether);

        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: bytes32(uint256(99)),
            ticketId: 0,
            user: user,
            nonce: 77,
            expiry: block.timestamp + 1 hours,
            ticketValue: 1 ether
        });

        vm.prank(owner);
        vm.expectRevert(RelayerEscrow.CommitAuthorizationMissing.selector);
        escrow.commitOnBehalf(user, address(market), auth, hex"");

        vm.prank(user);
        escrow.approveCommitAuthorization(address(market), auth);

        vm.prank(owner);
        escrow.commitOnBehalf(user, address(market), auth, hex"");
        assertEq(escrow.balances(user), 0, "ticket debited after approval");
    }

    function testCommitPauseAllowsFactory() external {
        vm.prank(owner);
        escrow.setMarketFactory(factory);

        vm.prank(factory);
        escrow.setCommitsPaused(true);
        assertTrue(escrow.commitsPaused());

        vm.prank(stranger);
        vm.expectRevert(RelayerEscrow.NotAuthorized.selector);
        escrow.setCommitsPaused(false);
    }

    function testCreditFromMarketRequiresAllowed() external {
        vm.prank(owner);
        escrow.setMarketFactory(address(this));
        DummyMarketGuard market = new DummyMarketGuard(address(this), address(escrow), address(token));
        escrow.registerMarket(address(market));

        vm.prank(stranger);
        vm.expectRevert(RelayerEscrow.UnknownMarket.selector);
        escrow.creditFromMarket(user, 1 ether);

        token.mint(address(market), 1 ether);
        vm.prank(address(market));
        token.approve(address(escrow), 1 ether);
        vm.prank(address(market));
        escrow.creditFromMarket(user, 1 ether);
        assertEq(escrow.balances(user), 1 ether);
    }
}

contract DummyMarketGuard is IRevealMarket {
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

    contract EscrowFactorySpoof {
        address private immutable SPOOFED_OWNER;

        constructor(address owner_) {
            SPOOFED_OWNER = owner_;
        }

        function owner() external view returns (address) {
            return SPOOFED_OWNER;
        }

        function attack(RelayerEscrow escrow, address attackerFactory) external {
            escrow.setMarketFactory(attackerFactory);
        }
    }
