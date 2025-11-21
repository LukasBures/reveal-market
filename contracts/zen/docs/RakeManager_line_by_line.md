# `RakeManager.sol` line-by-line guide

Line 1 — `// SPDX-License-Identifier: MIT`
States the contract is released under MIT so automated tools know the license.

Line 2 — `pragma solidity ^0.8.24;`
Pins the compiler version range to Solidity 0.8.24 (allowing compatible patch releases).

Line 3 — *(blank line)*
Provides visual separation between the pragma and the imports.

Line 4 — `import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";`
Pulls in the basic OpenZeppelin ownership helper.

Line 5 — `import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";`
Imports the two-step ownership transfer helper that requires the new owner to accept.

Line 6 — *(blank line)*
Spacer before local project imports.

Line 7 — `import {IRakeManager} from "./interfaces/IRakeManager.sol";`
Imports the rake manager interface the contract promises to implement.

Line 8 — *(blank line)*
Spacer before NatSpec description.

Line 9 — `/// @title RakeManager`
NatSpec title naming the contract.

Line 10 — `/// @notice Handles protocol rake distribution to the treasury.`
NatSpec notice summarizing the contract’s purpose.

Line 11 — `contract RakeManager is Ownable2Step, IRakeManager {`
Declares the contract, showing it inherits two-step ownership behavior and implements the interface.

Line 12 — `    event RakeTaken(address indexed token, uint256 totalAmount, uint256 rakeAmount, address treasury);`
Defines an event fired whenever rake is taken so off-chain systems can audit fees.

Line 13 — *(blank line)*
Spacer before constants.

Line 14 — `    uint256 public constant MAX_RAKE_BPS = 200;`
Defines the hard-coded maximum rake of 200 basis points (2%).

Line 15 — `    uint256 private constant BPS_DENOMINATOR = 10_000;`
Defines the denominator used when converting basis points to percentages.

Line 16 — *(blank line)*
Spacer before storage declarations.

Line 17 — `    address payable public treasury;`
Stores the treasury address that receives all rake transfers (payable for ETH support).

Line 18 — `    uint256 public rakeBps;`
Stores the currently configured rake rate in basis points.

Line 19 — *(blank line)*
Spacer before constructor.

Line 20 — `    constructor(address initialOwner, address payable treasury_, uint256 rakeBps_) Ownable(initialOwner) {`
Starts the constructor that sets initial ownership, treasury, and rake rate while calling the base Ownable constructor.

Line 21 — `        if (treasury_ == address(0)) revert InvalidTreasury();`
Rejects deployment if no treasury address is supplied.

Line 22 — `        if (rakeBps_ > MAX_RAKE_BPS) revert InvalidRakeBps();`
Ensures the initial rake rate does not exceed the maximum allowed.

Line 23 — `        treasury = treasury_;`
Stores the treasury address.

Line 24 — `        rakeBps = rakeBps_;`
Stores the initial rake rate.

Line 25 — `    }`
Closes the constructor.

Line 26 — *(blank line)*
Spacer before custom errors.

Line 27 — `    error InvalidTreasury();`
Defines the error used when a treasury address requirement is violated.

Line 28 — `    error InvalidRakeBps();`
Defines the error used when a rake rate exceeds the cap.

Line 29 — *(blank line)*
Spacer before functions.

Line 30 — `    /// @notice Updates the rake rate in basis points.`
Documentation for the next function describing its purpose.

Line 31 — `    /// @param newRate New rake rate (max 200 bps / 2%).`
NatSpec param note explaining the `newRate` argument.

Line 32 — `    function setRakeBps(uint256 newRate) external onlyOwner {`
Function allowing the owner to change the rake rate.

Line 33 — `        if (newRate > MAX_RAKE_BPS) revert InvalidRakeBps();`
Prevents setting a rate above the maximum.

Line 34 — `        rakeBps = newRate;`
Updates storage with the approved rate.

Line 35 — `    }`
Closes `setRakeBps`.

Line 36 — *(blank line)*
Spacer.

Line 37 — `    /// @notice Updates the treasury address receiving rake.`
NatSpec summary for the treasury setter.

Line 38 — `    /// @param newTreasury Treasury address.`
NatSpec parameter description.

Line 39 — `    function setTreasury(address payable newTreasury) external onlyOwner {`
Function allowing the owner to change the treasury recipient.

Line 40 — `        if (newTreasury == address(0)) revert InvalidTreasury();`
Prevents erasing the treasury by setting it to zero.

Line 41 — `        treasury = newTreasury;`
Stores the new treasury address.

Line 42 — `    }`
Closes `setTreasury`.

Line 43 — *(blank line)*
Spacer.

Line 44 — `    /// @inheritdoc IRakeManager`
Indicates the next function fulfils the interface definition.

Line 45 — `    function maxRakeBps() external pure override returns (uint256) {`
Implements the interface function reporting the cap.

Line 46 — `        return MAX_RAKE_BPS;`
Returns the constant maximum.

Line 47 — `    }`
Closes `maxRakeBps`.

Line 48 — *(blank line)*
Spacer.

Line 49 — `    /// @notice Deducts protocol rake from a contribution amount.`
NatSpec description for the rake deduction helper.

Line 50 — `    /// @param token Collateral token used for this calculation (address(0) for native ETH).`
Notes the meaning of the `token` argument.

Line 51 — `    /// @param amount Gross pool amount pre-rake.`
Describes the `amount` argument.

Line 52 — `    /// @return netAmount Net amount remaining after rake deduction.`
Documents the return value.

Line 53 — `    function takeRake(address token, uint256 amount, uint256 overrideBps)`
Begins the `takeRake` function signature.

Line 54 — `        external`
States the function’s visibility is external.

Line 55 — `        override`
Indicates it implements the interface.

Line 56 — `        returns (uint256 netAmount)`
Declares it returns the post-rake amount.

Line 57 — `    {`
Opens the function body.

Line 58 — `        uint256 appliedBps = overrideBps == 0 ? rakeBps : overrideBps;`
Chooses between the default rake rate and a per-call override.

Line 59 — `        if (appliedBps > MAX_RAKE_BPS) revert InvalidRakeBps();`
Ensures the applied rate never exceeds the cap.

Line 60 — `        uint256 rakeAmount = (amount * appliedBps) / BPS_DENOMINATOR;`
Calculates the actual rake amount by converting basis points into a percentage cut.

Line 61 — `        emit RakeTaken(token, amount, rakeAmount, treasury);`
Emits an event logging the rake details for off-chain accounting.

Line 62 — `        return amount - rakeAmount;`
Returns the net amount left for participants after the rake is removed.

Line 63 — `    }`
Closes `takeRake`.

Line 64 — `}`
Ends the contract.
