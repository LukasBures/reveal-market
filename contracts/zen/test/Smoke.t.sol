// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MessageHashUtils} from "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

import {MarketFactory} from "../src/MarketFactory.sol";
import {RevealMarket} from "../src/RevealMarket.sol";
import {RakeManager} from "../src/RakeManager.sol";
import {VerifierStub} from "../src/verifiers/VerifierStub.sol";

/// @notice End-to-end smoke test covering deploy → market creation → commit → settle → claim with a signed quote.
contract SmokeTest is Test {
    RakeManager private rakeManager;
    VerifierStub private verifier;
    MarketFactory private factory;
    RevealMarket private market;

    address payable private constant TREASURY = payable(address(0xBEEF));
    address private constant ORACLE = address(0xA11CE);
    uint256 private constant PRICING_SIGNER_KEY = 0xBEEF;
    address private pricingSigner;

    uint256 private commitDeadline;
    uint256 private revealDeadline;

    receive() external payable {}

    function setUp() public {
        pricingSigner = vm.addr(PRICING_SIGNER_KEY);
        rakeManager = new RakeManager(address(this), TREASURY, 0); // zero rake to simplify solvency math
        verifier = new VerifierStub();
        factory =
            new MarketFactory(address(new RevealMarket()), address(rakeManager), TREASURY, address(verifier), pricingSigner);

        commitDeadline = block.timestamp + 1 days;
        revealDeadline = commitDeadline + 1 days;
    }

    function testFullLifecycleSmoke() public {
        // Create market with min stake and tight commitment cap to exercise guards.
        MarketFactory.CreateMarketParams memory params;
        params.eventId = "SMOKE-1";
        params.commitDeadline = commitDeadline;
        params.revealDeadline = revealDeadline;
        params.oracle = ORACLE;
        params.payoutMultiplier = 1e18; // 1x for simplicity
        params.payoutCurve = RevealMarket.PayoutCurve.FixedOdds;
        params.floatAmount = 0;
        params.maxMarketSize = 5 ether;
        params.minCommitmentSize = 0.02 ether; // above on-chain floor of 0.01
        params.maxTicketsPerUser = 2;
        params.maxCommitments = 2;

        address deployed = factory.createMarket(params);
        market = RevealMarket(payable(deployed));

        // Prepare a signed quote for commitWithQuote.
        RevealMarket.SignedQuote memory quote = _buildQuote(
            0.02 ether, // stake
            0, // outcome YES
            block.timestamp + 1 hours,
            keccak256("smoke-quote"),
            address(this),
            1_000e18
        );

        vm.deal(address(this), quote.stakeZen);
        market.commitWithQuote{value: quote.stakeZen}(quote.outcomeId, quote.stakeZen, keccak256("salt"), quote);
        assertEq(market.commitmentsCount(), 1);

        // Lock and settle with stub verifier (auto-true).
        vm.warp(commitDeadline + 1);
        market.lock();
        vm.prank(ORACLE);
        market.postResult(0);

        uint256[10] memory signals;
        signals[0] = uint256(market.commitmentsRoot());
        signals[1] = market.marketId();
        signals[2] = 0;
        signals[3] = quote.stakeZen;
        signals[4] = quote.stakeZen; // liability = stake * 1x
        signals[5] = 0; // rake bps
        signals[6] = quote.stakeZen;
        signals[7] = 0;
        signals[8] = uint256(market.circuitHash());
        signals[9] = 0;

        market.verifyAndSettle("", signals);
        assertEq(uint256(market.phase()), uint256(RevealMarket.Phase.Settled));

        // Claim winnings.
        bytes32[] memory proof = new bytes32[](0);
        uint256 balBefore = address(this).balance;
        market.claim(0, 0, keccak256("salt"), 0, proof);
        assertEq(address(this).balance, balBefore + quote.stakeZen);
    }

    function _buildQuote(
        uint256 stake,
        uint256 outcome,
        uint256 expiry,
        bytes32 quoteId,
        address expectedUser,
        uint256 zenUsd
    ) private view returns (RevealMarket.SignedQuote memory quote) {
        quote = RevealMarket.SignedQuote({
            quoteId: quoteId,
            stakeZen: stake,
            zenUsd: zenUsd,
            expiry: expiry,
            outcomeId: outcome,
            expectedUser: expectedUser,
            signature: ""
        });
        bytes32 digest = keccak256(
            abi.encodePacked(
                "QUOTE_V1",
                block.chainid,
                address(market),
                quote.expectedUser,
                quote.outcomeId,
                quote.stakeZen,
                quote.zenUsd,
                quote.expiry,
                quote.quoteId
            )
        );
        (uint8 v, bytes32 r, bytes32 s) =
            vm.sign(PRICING_SIGNER_KEY, MessageHashUtils.toEthSignedMessageHash(digest));
        quote.signature = abi.encodePacked(r, s, v);
    }
}
