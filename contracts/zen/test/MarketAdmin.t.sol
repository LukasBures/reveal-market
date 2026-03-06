// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {Test} from "forge-std/Test.sol";
import {MessageHashUtils} from "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

import {MarketFactory} from "../src/MarketFactory.sol";
import {ProtocolPool} from "../src/ProtocolPool.sol";
import {RelayerEscrow} from "../src/RelayerEscrow.sol";
import {RevealMarket} from "../src/RevealMarket.sol";
import {IRevealMarket} from "../src/interfaces/IRevealMarket.sol";
import {MockVerifier} from "./mocks/MockVerifier.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {PoseidonTestUtils} from "./utils/PoseidonTestUtils.sol";

contract MarketAdminTest is Test, PoseidonTestUtils {
    RelayerEscrow private relayerEscrow;
    ProtocolPool private protocolPool;
    MarketFactory private factory;
    RevealMarket private implementation;
    MockVerifier private verifier;
    MockERC20 private token;
    RevealMarket private market;

    uint256 private relayerKey = 0xBEEF;
    address private relayerOwner = vm.addr(relayerKey);
    address private oracle = makeAddr("oracle");
    uint256 private authKey = 0xA11CE;
    address private authSigner = vm.addr(authKey);
    address private user = makeAddr("user");
    bytes32 private circuitHash = keccak256("settlement");
    uint256 private ticketSize = 1 ether;
    uint256 private protocolCap = 3 ether;
    uint256 private maxCommitments = 8;
    uint256 private commitDeadline;

    function setUp() external {
        token = new MockERC20();
        relayerEscrow = new RelayerEscrow(relayerOwner, IERC20(address(token)));
        protocolPool = new ProtocolPool(address(this), IERC20(address(token)));
        verifier = new MockVerifier(circuitHash);
        implementation = new RevealMarket();
        factory = new MarketFactory(address(implementation), protocolPool, relayerEscrow, address(token), address(this));

        protocolPool.setMarketFactory(address(factory));
        vm.prank(relayerOwner);
        relayerEscrow.setMarketFactory(address(factory));
        factory.setVerifierApproval(address(verifier), true);

        commitDeadline = block.timestamp + 1 days;

        MarketFactory.CreateMarketParams memory params = MarketFactory.CreateMarketParams({
            oracle: oracle,
            verifier: address(verifier),
            circuitHash: circuitHash,
            commitDeadline: commitDeadline,
            fixedTicketSize: ticketSize,
            maxCommitments: maxCommitments,
            authorizationSigner: authSigner,
            protocolLiabilityCap: protocolCap
        });

        market = RevealMarket(payable(factory.createMarket(params)));

        token.mint(address(this), 1_000 ether);
        token.approve(address(protocolPool), 1_000 ether);
        protocolPool.deposit(1_000 ether);
    }

    function testAuthorizationSignerRotationDuringCommit() external {
        uint256 newKey = 0xBEEF;
        address newSigner = vm.addr(newKey);
        vm.prank(address(this));
        factory.updateAuthorizationSigner(address(market), newSigner);
        assertEq(market.authorizationSigner(), newSigner, "signer rotated");

        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: _leaf(0, 0, ticketSize, ticketSize, _salt("leaf"), user),
            ticketId: 0,
            user: user,
            nonce: 1,
            expiry: block.timestamp + 4 hours,
            ticketValue: ticketSize
        });

        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);

        bytes memory badSig = _signAuth(auth, authKey);
        vm.expectRevert(RevealMarket.InvalidSignature.selector);
        vm.prank(relayerOwner);
        relayerEscrow.commitOnBehalf(user, address(market), auth, badSig);

        bytes memory goodSig = _signAuth(auth, newKey);
        _approveAndCommit(relayerEscrow, relayerOwner, user, address(market), auth, goodSig);
        assertEq(market.totalEscrow(), ticketSize - (ticketSize * market.rakeBps()) / 10_000, "commit succeeded");
    }

    function testOracleRotation() external {
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: _leaf(0, 0, ticketSize, ticketSize, _salt("leaf2"), user),
            ticketId: 0,
            user: user,
            nonce: 2,
            expiry: block.timestamp + 4 hours,
            ticketValue: ticketSize
        });
        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);
        bytes memory sig = _signAuth(auth, authKey);
        _approveAndCommit(relayerEscrow, relayerOwner, user, address(market), auth, sig);

        address newOracle = makeAddr("newOracle");
        vm.prank(address(this));
        factory.updateOracle(address(market), newOracle);
        assertEq(market.oracle(), newOracle);

        vm.warp(commitDeadline + 1);
        bytes32[] memory leaves = new bytes32[](1);
        leaves[0] = auth.commitment;
        bytes32 root = _buildBatchRoot(leaves, 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = root;
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        bytes memory relayerSig = _signRelayer(roots, counts);

        vm.prank(oracle);
        vm.expectRevert(RevealMarket.NotOracle.selector);
        market.lockBatches(roots, counts, relayerSig);

        vm.prank(newOracle);
        market.lockBatches(roots, counts, relayerSig);
    }

    function testRelayerRotationAllowsNewRelayer() external {
        RelayerEscrow newRelayer = new RelayerEscrow(makeAddr("newRelayerOwner"), IERC20(address(token)));
        vm.prank(newRelayer.owner());
        newRelayer.setMarketFactory(address(factory));

        vm.prank(address(this));
        factory.updateMarketRelayer(address(market), newRelayer);
        assertEq(market.relayerEscrow(), address(newRelayer));

        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: _leaf(0, 0, ticketSize, ticketSize, _salt("leaf3"), user),
            ticketId: 0,
            user: user,
            nonce: 3,
            expiry: block.timestamp + 4 hours,
            ticketValue: ticketSize
        });
        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(newRelayer), ticketSize);
        vm.prank(user);
        newRelayer.deposit(ticketSize);
        bytes memory sig = _signAuth(auth, authKey);

        _approveAndCommit(newRelayer, newRelayer.owner(), user, address(market), auth, sig);
        assertEq(market.totalEscrow(), ticketSize - (ticketSize * market.rakeBps()) / 10_000);

        vm.expectRevert(RevealMarket.NotRelayer.selector);
        vm.prank(makeAddr("stranger"));
        market.commitWithAuthorization(auth, sig);
    }

    function testProtocolLiabilityCapUpdateStopsAfterSettlement() external {
        uint256 newCap = 5 ether;
        vm.prank(address(this));
        factory.updateProtocolLiabilityCap(address(market), newCap);
        assertEq(market.protocolLiabilityCap(), newCap);
        assertEq(protocolPool.liabilityCap(address(market)), newCap);

        uint256 netTicket = ticketSize - (ticketSize * market.rakeBps()) / 10_000;
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: _leaf(0, 1, netTicket, netTicket, _salt("leaf4"), user),
            ticketId: 0,
            user: user,
            nonce: 4,
            expiry: block.timestamp + 4 hours,
            ticketValue: ticketSize
        });
        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);
        bytes memory sig = _signAuth(auth, authKey);
        _approveAndCommit(relayerEscrow, relayerOwner, user, address(market), auth, sig);

        vm.warp(commitDeadline + 1);
        bytes32 root = _lockSingleBatch(oracle, auth.commitment);
        vm.prank(oracle);
        market.postResult(1);
        uint256[10] memory signals = [
            uint256(root),
            uint256(1),
            uint256(1),
            netTicket,
            netTicket,
            market.rakeBps(),
            netTicket,
            uint256(0),
            uint256(circuitHash),
            uint256(0)
        ];

        vm.prank(oracle);
        market.verifyAndSettle("", signals);

        vm.prank(address(this));
        vm.expectRevert(RevealMarket.InvalidPhase.selector);
        factory.updateProtocolLiabilityCap(address(market), newCap + 1);
    }

    function _lockSingleBatch(address caller, bytes32 leaf) internal returns (bytes32) {
        bytes32[] memory leaves = new bytes32[](1);
        leaves[0] = leaf;
        bytes32 root = _buildBatchRoot(leaves, 1);
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = root;
        uint16[] memory counts = new uint16[](1);
        counts[0] = 1;
        bytes memory relayerSig = _signRelayer(roots, counts);
        vm.prank(caller);
        market.lockBatches(roots, counts, relayerSig);
        return root;
    }

    function _approveAndCommit(
        RelayerEscrow escrow,
        address relayerCaller,
        address commitUser,
        address marketAddr,
        IRevealMarket.CommitAuth memory auth,
        bytes memory sig
    ) internal {
        vm.prank(relayerCaller);
        escrow.commitOnBehalf(commitUser, marketAddr, auth, sig);
    }

    function _signAuth(IRevealMarket.CommitAuth memory auth, uint256 privKey) private view returns (bytes memory) {
        bytes32 digest = MessageHashUtils.toEthSignedMessageHash(
            keccak256(
                abi.encodePacked(
                    address(market),
                    market.marketId(),
                    auth.ticketId,
                    auth.commitment,
                    auth.user,
                    auth.nonce,
                    auth.expiry,
                    auth.ticketValue,
                    block.chainid
                )
            )
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(privKey, digest);
        return abi.encodePacked(r, s, v);
    }

    function _signRelayer(bytes32[] memory roots, uint16[] memory counts) private view returns (bytes memory) {
        bytes32 digest = MessageHashUtils.toEthSignedMessageHash(
            keccak256(abi.encode(address(market), address(factory), market.marketId(), roots, counts, block.chainid))
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(relayerKey, digest);
        return abi.encodePacked(r, s, v);
    }

    function _leaf(uint256 ticketId, uint256 outcomeId, uint256 amount, uint256 payout, bytes32 salt, address leafUser)
        internal
        pure
        returns (bytes32)
    {
        return _poseidonLeaf(ticketId, outcomeId, amount, payout, salt, leafUser);
    }

    function testRakeBoundsAndOverride() external {
        vm.prank(address(this));
        vm.expectRevert(abi.encodeWithSelector(RevealMarket.InvalidInit.selector));
        factory.setMarketRake(address(market), 20_000);

        vm.prank(address(this));
        factory.setMarketRake(address(market), 500);
        assertEq(market.rakeBps(), 500);
    }

    function testRakeLockedAfterFirstCommit() external {
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: _leaf(0, 0, ticketSize, ticketSize, _salt("rake-lock"), user),
            ticketId: 0,
            user: user,
            nonce: 88,
            expiry: block.timestamp + 4 hours,
            ticketValue: ticketSize
        });
        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);
        bytes memory sig = _signAuth(auth, authKey);
        _approveAndCommit(relayerEscrow, relayerOwner, user, address(market), auth, sig);

        vm.prank(address(this));
        vm.expectRevert(RevealMarket.RakeLocked.selector);
        factory.setMarketRake(address(market), 300);
    }

    function testExtendDeadlinesAndGuards() external {
        uint256 newCommit = commitDeadline + 1 hours;
        vm.prank(address(this));
        factory.extendMarketCommitDeadline(address(market), newCommit);
        assertEq(market.commitDeadline(), newCommit);

        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: _leaf(0, 0, ticketSize, ticketSize, _salt("deadline-leaf"), user),
            ticketId: 0,
            user: user,
            nonce: 77,
            expiry: block.timestamp + 4 hours,
            ticketValue: ticketSize
        });
        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);
        bytes memory sig = _signAuth(auth, authKey);
        _approveAndCommit(relayerEscrow, relayerOwner, user, address(market), auth, sig);

        vm.warp(commitDeadline + 2 days);
        _lockSingleBatch(oracle, auth.commitment);

        vm.expectRevert(RevealMarket.InvalidPhase.selector);
        vm.prank(address(this));
        factory.extendMarketCommitDeadline(address(market), newCommit + 1 days);
    }

    function testCommitDeadlineExtensionIsOneShot() external {
        uint256 firstExtension = commitDeadline + 2 hours;
        vm.prank(address(this));
        factory.extendMarketCommitDeadline(address(market), firstExtension);
        assertEq(market.commitDeadline(), firstExtension);

        vm.prank(address(this));
        vm.expectRevert(RevealMarket.CommitDeadlineAlreadyExtended.selector);
        factory.extendMarketCommitDeadline(address(market), firstExtension + 1 hours);
    }

    function testCommitDeadlineExtensionRejectsTooFar() external {
        uint256 tooFar = commitDeadline + market.MAX_COMMIT_DEADLINE_EXTENSION() + 1;
        vm.prank(address(this));
        vm.expectRevert(RevealMarket.DeadlineTooFar.selector);
        factory.extendMarketCommitDeadline(address(market), tooFar);
    }

    function testRelayerEscrowRotationGuard() external {
        RelayerEscrow newEscrow = new RelayerEscrow(makeAddr("newRelayerOwnerGuard"), IERC20(address(token)));
        vm.prank(newEscrow.owner());
        newEscrow.setMarketFactory(address(factory));

        vm.prank(address(this));
        factory.updateMarketRelayer(address(market), newEscrow);
        assertEq(market.relayerEscrow(), address(newEscrow));

        vm.expectRevert(MarketFactory.InvalidRelayer.selector);
        vm.prank(address(this));
        factory.updateMarketRelayer(address(market), RelayerEscrow(address(0)));
    }

    function testRelayerRotationLockedAfterFirstCommit() external {
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: _leaf(0, 0, ticketSize, ticketSize, _salt("relayer-rotation-lock"), user),
            ticketId: 0,
            user: user,
            nonce: 404,
            expiry: block.timestamp + 4 hours,
            ticketValue: ticketSize
        });
        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);
        bytes memory sig = _signAuth(auth, authKey);
        _approveAndCommit(relayerEscrow, relayerOwner, user, address(market), auth, sig);

        RelayerEscrow newEscrow = new RelayerEscrow(makeAddr("rotated-owner"), IERC20(address(token)));
        vm.prank(newEscrow.owner());
        newEscrow.setMarketFactory(address(factory));

        vm.prank(address(this));
        vm.expectRevert(MarketFactory.RelayerRotationLocked.selector);
        factory.updateMarketRelayer(address(market), newEscrow);
    }

    function testRelayerBalanceMigration() external {
        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);
        assertEq(relayerEscrow.balances(user), ticketSize);

        RelayerEscrow newEscrow = new RelayerEscrow(makeAddr("migration-relayer-owner"), IERC20(address(token)));
        vm.prank(newEscrow.owner());
        newEscrow.setMarketFactory(address(factory));

        vm.prank(address(this));
        factory.updateMarketRelayer(address(market), newEscrow);

        address[] memory users = new address[](1);
        users[0] = user;
        vm.prank(address(this));
        factory.migrateMarketRelayerBalances(address(market), relayerEscrow, users);

        assertEq(relayerEscrow.balances(user), 0, "old relayer drained");
        assertEq(newEscrow.balances(user), ticketSize, "new relayer credited");
    }

    function testProtocolPoolMigrationForMarket() external {
        ProtocolPool newPool = new ProtocolPool(address(this), IERC20(address(token)));
        newPool.setMarketFactory(address(factory));

        vm.prank(address(this));
        factory.updateMarketProtocolPool(address(market), newPool);

        assertEq(market.protocolPool(), address(newPool));
        assertEq(newPool.liabilityCap(address(market)), market.protocolLiabilityCap());
    }

    function testProtocolPoolMigrationLockedAfterFirstCommit() external {
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: _leaf(0, 0, ticketSize, ticketSize, _salt("pool-lock"), user),
            ticketId: 0,
            user: user,
            nonce: 909,
            expiry: block.timestamp + 4 hours,
            ticketValue: ticketSize
        });
        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);
        bytes memory sig = _signAuth(auth, authKey);
        _approveAndCommit(relayerEscrow, relayerOwner, user, address(market), auth, sig);

        ProtocolPool newPool = new ProtocolPool(address(this), IERC20(address(token)));
        newPool.setMarketFactory(address(factory));

        vm.prank(address(this));
        vm.expectRevert(MarketFactory.ProtocolPoolRotationLocked.selector);
        factory.updateMarketProtocolPool(address(market), newPool);
    }

    function testAuthorizationSignerGuard() external {
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: _leaf(0, 0, ticketSize, ticketSize, _salt("guard-leaf"), user),
            ticketId: 0,
            user: user,
            nonce: 9,
            expiry: block.timestamp + 4 hours,
            ticketValue: ticketSize
        });
        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);
        bytes memory sig = _signAuth(auth, authKey);
        _approveAndCommit(relayerEscrow, relayerOwner, user, address(market), auth, sig);

        vm.prank(address(this));
        factory.updateAuthorizationSigner(address(market), makeAddr("newSigner"));
        vm.warp(commitDeadline + 2 days);
        _lockSingleBatch(oracle, auth.commitment);
        vm.expectRevert(RevealMarket.InvalidPhase.selector);
        vm.prank(address(this));
        factory.updateAuthorizationSigner(address(market), makeAddr("newerSigner"));
    }

    function testPauseControlsBlockCommitsAndClaims() external {
        bytes32 leaf = _leaf(0, 0, ticketSize, ticketSize, _salt("pause-commit"), user);
        IRevealMarket.CommitAuth memory auth = IRevealMarket.CommitAuth({
            commitment: leaf,
            ticketId: 0,
            user: user,
            nonce: 55,
            expiry: block.timestamp + 4 hours,
            ticketValue: ticketSize
        });

        token.mint(user, ticketSize);
        vm.prank(user);
        token.approve(address(relayerEscrow), ticketSize);
        vm.prank(user);
        relayerEscrow.deposit(ticketSize);

        vm.prank(address(this));
        factory.setMarketCommitsPaused(address(market), true);

        bytes memory sig = _signAuth(auth, authKey);
        vm.expectRevert(RevealMarket.CommitsPaused.selector);
        vm.prank(relayerOwner);
        relayerEscrow.commitOnBehalf(user, address(market), auth, sig);

        vm.prank(address(this));
        factory.setMarketCommitsPaused(address(market), false);

        _approveAndCommit(relayerEscrow, relayerOwner, user, address(market), auth, sig);

        vm.warp(commitDeadline + 1);
        bytes32 root = _lockSingleBatch(oracle, auth.commitment);
        vm.prank(oracle);
        market.postResult(0);
        uint256 netTicket = ticketSize - (ticketSize * market.rakeBps()) / 10_000;
        uint256[10] memory signals = [
            uint256(root),
            market.marketId(),
            uint256(0),
            netTicket,
            netTicket,
            market.rakeBps(),
            netTicket,
            uint256(0),
            uint256(circuitHash),
            uint256(0)
        ];
        vm.prank(oracle);
        market.verifyAndSettle("", signals);

        bytes32[] memory leaves = new bytes32[](1);
        leaves[0] = auth.commitment;
        bytes32[] memory proof = _buildMerkleProof(leaves, 1, 0);

        vm.prank(address(this));
        factory.setMarketClaimsPaused(address(market), true);
        vm.prank(relayerOwner);
        vm.expectRevert(RevealMarket.ClaimsPaused.selector);
        market.claim(user, 0, 0, netTicket, netTicket, _salt("pause-commit"), proof);

        vm.prank(address(this));
        factory.setMarketClaimsPaused(address(market), false);
    }
}
