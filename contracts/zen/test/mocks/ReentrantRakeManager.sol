// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IRakeManager} from "../../src/interfaces/IRakeManager.sol";
import {RevealMarket} from "../../src/RevealMarket.sol";

/// @dev Test helper that attempts to reenter RevealMarket during rake calculation.
contract ReentrantRakeManager is IRakeManager {
    enum AttackMode {
        None,
        EmergencySettle,
        CancelMarket
    }

    RevealMarket public immutable MARKET;
    AttackMode public mode;
    bytes32 public reenterOutcome;
    uint256 public reenterWinningPool;
    string public cancelReason;

    bool private _entered;

    constructor(RevealMarket market_) {
        MARKET = market_;
    }

    function setAttackEmergency(bytes32 outcomeHash, uint256 winningPool) external {
        mode = AttackMode.EmergencySettle;
        reenterOutcome = outcomeHash;
        reenterWinningPool = winningPool;
        _entered = false;
    }

    function setAttackCancel(string calldata reason) external {
        mode = AttackMode.CancelMarket;
        cancelReason = reason;
        _entered = false;
    }

    function clearAttack() external {
        mode = AttackMode.None;
        _entered = false;
    }

    function triggerSettlement(bytes32 outcomeHash, uint256 declaredWinningPool) external {
        _entered = false;
        MARKET.emergencySettle(outcomeHash, declaredWinningPool);
    }

    function takeRake(address, uint256 amount, uint256) external override returns (uint256) {
        if (_entered) return amount;
        _entered = true;

        if (mode == AttackMode.EmergencySettle) {
            MARKET.emergencySettle(reenterOutcome, reenterWinningPool);
        } else if (mode == AttackMode.CancelMarket) {
            MARKET.cancelMarket(cancelReason);
        }

        _entered = false;
        return amount;
    }

    function maxRakeBps() external pure returns (uint256) {
        return 200;
    }

    function rakeBps() external pure returns (uint256) {
        return 100;
    }
}
