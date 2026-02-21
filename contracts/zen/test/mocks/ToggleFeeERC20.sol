// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {MockERC20} from "./MockERC20.sol";

/// @notice Test token that can switch between vanilla ERC20 and fee-on-transfer behavior.
contract ToggleFeeERC20 is MockERC20 {
    uint256 public feeBps;
    bool public senderSurchargeMode;

    error InvalidFeeBps();

    function setFeeBps(uint256 newFeeBps) external {
        if (newFeeBps > 10_000) revert InvalidFeeBps();
        feeBps = newFeeBps;
    }

    function setSenderSurchargeMode(bool enabled) external {
        senderSurchargeMode = enabled;
    }

    function transfer(address to, uint256 amount) public override returns (bool) {
        _transferWithFee(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) public override returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        if (allowed != type(uint256).max) {
            allowance[from][msg.sender] = allowed - amount;
        }
        _transferWithFee(from, to, amount);
        return true;
    }

    function _transferWithFee(address from, address to, uint256 amount) internal {
        uint256 fee = (amount * feeBps) / 10_000;
        uint256 received = senderSurchargeMode ? amount : amount - fee;
        uint256 senderDebit = senderSurchargeMode ? amount + fee : amount;

        balanceOf[from] -= senderDebit;
        unchecked {
            balanceOf[to] += received;
        }
        emit Transfer(from, to, received);

        if (fee != 0) {
            totalSupply -= fee;
            emit Transfer(from, address(0), fee);
        }
    }
}
