// SPDX-License-Identifier: MIT
pragma solidity ^0.8.33;

import {ERC20} from "solmate/tokens/ERC20.sol";

contract MockERC20 is ERC20 {
    constructor() ERC20("Mock ZEN", "ZEN", 18) {}

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}
