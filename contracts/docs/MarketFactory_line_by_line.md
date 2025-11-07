# `MarketFactory.sol` line-by-line guide

The notes below walk through every line of `contracts/src/MarketFactory.sol`, restating what the code is doing in plain English so it is easier to follow. Each entry mentions the original source line and explains the intent.

Line 1 — `// SPDX-License-Identifier: MIT`  
Declares that the contract is released under the MIT license so tooling knows the terms.

Line 2 — `pragma solidity ^0.8.24;`  
Locks compilation to Solidity 0.8.24 (or compatible newer patch versions) to avoid compiler drift.

Line 3 — *(blank line)*  
Separates the pragma/license block from the imports for readability.

Line 4 — `import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";`  
Pulls in OpenZeppelin’s `Ownable`, which tracks an owner address with basic access control helpers.

Line 5 — `import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";`  
Imports OpenZeppelin’s two-step ownership transfer helper so ownership hand-offs require acceptance.

Line 6 — `import {Clones} from "@openzeppelin/contracts/proxy/Clones.sol";`  
Brings in the minimal proxy cloning helpers used to create cheap instances of `RevealMarket`.

Line 7 — *(blank line)*  
Visual separator before local project imports.

Line 8 — `import {RevealMarket} from "./RevealMarket.sol";`  
Imports the RevealMarket implementation contract so the factory can call its functions.

Line 9 — `import {IRakeManager} from "./interfaces/IRakeManager.sol";`  
Imports the rake manager interface so the factory can check rake caps.

Line 10 — *(blank line)*  
Separates imports from the NatSpec header.

Line 11 — `/// @title MarketFactory`  
NatSpec title stating the contract’s name for documentation.

Line 12 — `/// @notice Deploys RevealMarket clones with shared configuration.`  
NatSpec notice summarizing that this contract creates RevealMarket instances with shared settings.

Line 13 — `contract MarketFactory is Ownable2Step {`  
Begins the contract definition and declares it inherits from `Ownable2Step` for ownership management.

Line 14 — `    using Clones for address;`  
Enables the `clone()` extension method on `address` types, letting `implementation.clone()` be called.

Line 15 — *(blank line)*  
Spacer before event declarations.

Line 16 — `    event MarketCreated(`  
Starts the declaration of the `MarketCreated` event emitted after a new market is deployed.

Line 17 — `        address indexed market,`  
Declares the first event parameter: indexed deployed market address.

Line 18 — `        string indexed eventId,`  
Adds the second parameter: indexed market event identifier string for filtering.

Line 19 — `        uint256 commitDeadline,`  
Records the commit phase deadline pushed with the event for easier off-chain tracking.

Line 20 — `        uint256 revealDeadline,`  
Records the reveal phase deadline in the event payload.

Line 21 — `        address collateral,`  
Includes the collateral token (or zero for native) used by the deployed market.

Line 22 — `        uint256 rakeBps`  
Includes the rake basis points override applied to the market for transparency.

Line 23 — `    );`  
Closes the `MarketCreated` event definition.

Line 24 — `    event CollateralStatusUpdated(address indexed collateral, bool allowed);`  
Defines an event that fires whenever a collateral token’s allowlist status changes.

Line 25 — `    event DefaultCollateralUpdated(address indexed collateral);`  
Event emitted when the default collateral pointer is updated.

Line 26 — `    event AllowlistPauseSet(bool paused, address indexed triggeredBy);`  
Event showing when the collateral allowlist is paused or unpaused and by whom.

Line 27 — `    event GuardianUpdated(address indexed newGuardian);`  
Event logging guardian role updates so operators know who currently shares control.

Line 28 — `    event GlobalCommitPauseSet(bool paused, address indexed triggeredBy);`  
Emitted whenever the factory sets the global commit pause flag.

Line 29 — `    event GlobalClaimPauseSet(bool paused, address indexed triggeredBy);`  
Emitted whenever the factory toggles the global claim pause flag.

Line 30 — `    event MarketPaused(address indexed market, bool commitPaused, bool claimPaused, address indexed triggeredBy);`  
Event capturing per-market commit/claim pause changes and the caller who performed them.

Line 31 — `    event MarketGuardianUpdated(address indexed market, address indexed newGuardian);`  
Event broadcast when a specific market’s guardian is changed.

Line 32 — `    event MarketMetadataUpdated(address indexed market, string metadataURI);`  
Event placeholder for metadata updates (currently unused, but reserved for future features).

Line 33 — *(blank line)*  
Spacer before state variable declarations.

Line 34 — `    address public implementation;`  
Public storage slot pointing to the RevealMarket implementation that will be cloned.

Line 35 — `    address public rakeManager;`  
Public pointer to the rake manager contract used to cap fee overrides.

Line 36 — `    address public treasury;`  
Stores the treasury address that ultimately receives collected rake.

Line 37 — `    address public verifier;`  
Stores the zero-knowledge verifier address that markets should trust.

Line 38 — `    address public defaultCollateral;`  
Keeps track of the default collateral token address used when none is specified.

Line 39 — `    address public guardian;`  
Holds the guardian address empowered to pause or emergency-control markets.

Line 40 — `    bool public allowlistPaused;`  
Boolean flag noting whether collateral allowlist changes or usage are currently paused.

Line 41 — `    bool public globalCommitPaused;`  
Flag that downstream markets read to know if commits should be globally paused.

Line 42 — `    bool public globalClaimPaused;`  
Flag that downstream markets read to know if claims should be globally paused.

Line 43 — *(blank line)*  
Separates public state from private/internal collections.

Line 44 — `    address[] private _markets;`  
Private array storing addresses of every market the factory has created.

Line 45 — `    mapping(address => bool) public isMarket;`  
Public mapping allowing quick verification that an address came from this factory.

Line 46 — `    mapping(address => bool) public isCollateralAllowed;`  
Public mapping recording which collateral tokens are permitted for new markets.

Line 47 — *(blank line)*  
Spacer before the constructor.

Line 48 — `    constructor(`  
Begins the constructor that sets initial shared configuration.

Line 49 — `        address implementation_,`  
Constructor parameter for the RevealMarket implementation address.

Line 50 — `        address rakeManager_,`  
Constructor parameter for the rake manager contract.

Line 51 — `        address treasury_,`  
Constructor parameter for the treasury that receives rake.

Line 52 — `        address verifier_,`  
Constructor parameter for the verifier contract address.

Line 53 — `        address collateral_`  
Constructor parameter for the default collateral token address.

Line 54 — `    )`  
Closes the constructor’s parameter list.

Line 55 — `        Ownable(msg.sender)`  
Forwards the deployer’s address into the `Ownable` base constructor to set the initial owner.

Line 56 — `    {`  
Opens the constructor body.

Line 57 — `        if (`  
Starts an if block that validates constructor parameters for zero addresses.

Line 58 — `            implementation_ == address(0) ||`  
Checks that the implementation pointer is not the zero address.

Line 59 — `            rakeManager_ == address(0) ||`  
Requires the rake manager pointer to be set.

Line 60 — `            treasury_ == address(0) ||`  
Requires the treasury pointer to be set.

Line 61 — `            verifier_ == address(0)`  
Requires the verifier pointer to be set.

Line 62 — `        ) revert ZeroAddress();`  
Reverts with `ZeroAddress` if any required pointer was missing.

Line 63 — *(blank line)*  
Visual separator between validation and state assignment.

Line 64 — `        implementation = implementation_;`  
Stores the implementation address for later cloning.

Line 65 — `        rakeManager = rakeManager_;`  
Stores the rake manager pointer.

Line 66 — `        treasury = treasury_;`  
Stores the treasury pointer.

Line 67 — `        verifier = verifier_;`  
Stores the verifier pointer.

Line 68 — `        defaultCollateral = collateral_;`  
Sets the initial default collateral to the provided token (can be zero to allow manual choice later).

Line 69 — *(blank line)*  
Separates the next configuration block.

Line 70 — `        if (collateral_ != address(0)) {`  
If a non-zero default collateral was provided, begin allowlisting it.

Line 71 — `            isCollateralAllowed[collateral_] = true;`  
Marks that collateral as allowed so future markets can use it.

Line 72 — `        }`  
Closes the conditional block.

Line 73 — `        isCollateralAllowed[address(0)] = true;`  
Always allow the zero address sentinel so markets can request “use default collateral”.

Line 74 — *(blank line)*  
Separates guardian setup from collateral logic.

Line 75 — `        guardian = msg.sender;`  
Sets the deploying address as the initial guardian.

Line 76 — `        emit GuardianUpdated(msg.sender);`  
Emits the guardian update event so off-chain observers record the initial guardian.

Line 77 — `    }`  
Closes the constructor body.

Line 78 — *(blank line)*  
Spacer before the error declarations.

Line 79 — `    // ───────────────────────────────`  
Decorative comment line introducing the “Errors” section.

Line 80 — `    // Errors`  
Section heading comment.

Line 81 — `    // ───────────────────────────────`  
Decorative divider continuing the section heading.

Line 82 — `    error ZeroAddress();`  
Custom error used whenever a required address parameter is empty.

Line 83 — `    error InvalidDeadlines();`  
Custom error thrown when commit/reveal deadlines are illogical.

Line 84 — `    error CollateralNotAllowed(address collateral);`  
Custom error thrown when a collateral token has not been allowlisted.

Line 85 — `    error CannotDisableDefaultCollateral();`  
Custom error thrown when trying to block the current default collateral.

Line 86 — `    error AllowlistPaused();`  
Custom error used when an action is blocked because the allowlist is paused.

Line 87 — `    error NotGuardianOrOwner();`  
Custom error for unauthorized callers attempting guardian/owner actions.

Line 88 — `    error UnknownMarket();`  
Custom error fired when the target market was not spawned by this factory.

Line 89 — `    error InvalidRakeBps();`  
Custom error thrown when a rake override exceeds allowed limits.

Line 90 — *(blank line)*  
Spacer before the modifier section.

Line 91 — `    // ───────────────────────────────`  
Divider comment for the modifier section.

Line 92 — `    // Modifiers`  
Section heading for modifiers.

Line 93 — `    // ───────────────────────────────`  
Closing divider line for the heading.

Line 94 — `    modifier onlyGuardianOrOwner() {`  
Starts the `onlyGuardianOrOwner` modifier definition that gates functions.

Line 95 — `        _onlyGuardianOrOwner();`  
Calls the internal helper to perform the actual authorization check.

Line 96 — `        _;`  
Executes the rest of the wrapped function if the caller passed the check.

Line 97 — `    }`  
Closes the modifier definition.

Line 98 — *(blank line)*  
Spacer ahead of admin function section.

Line 99 — `    // ───────────────────────────────`  
Divider comment for admin setter section.

Line 100 — `    // Admin setters`  
Section heading describing the next group of functions.

Line 101 — `    // ───────────────────────────────`  
Ending divider line.

Line 102 — `    function setImplementation(address implementation_) external onlyOwner {`  
Begins the admin function allowing the owner to update the implementation pointer.

Line 103 — `        if (implementation_ == address(0)) revert ZeroAddress();`  
Prevents accidentally clearing the implementation pointer.

Line 104 — `        implementation = implementation_;`  
Stores the new implementation address.

Line 105 — `    }`  
Closes `setImplementation`.

Line 106 — *(blank line)*  
Spacer between setter functions.

Line 107 — `    function setRakeManager(address rakeManager_) external onlyOwner {`  
Starts the setter for the rake manager address.

Line 108 — `        if (rakeManager_ == address(0)) revert ZeroAddress();`  
Disallows zero rake manager addresses.

Line 109 — `        rakeManager = rakeManager_;`  
Stores the new rake manager pointer.

Line 110 — `    }`  
Ends `setRakeManager`.

Line 111 — *(blank line)*  
Spacer.

Line 112 — `    function setTreasury(address treasury_) external onlyOwner {`  
Opens the treasury setter function restricted to the owner.

Line 113 — `        if (treasury_ == address(0)) revert ZeroAddress();`  
Prevents wiping the treasury pointer.

Line 114 — `        treasury = treasury_;`  
Stores the replacement treasury address.

Line 115 — `    }`  
Closes `setTreasury`.

Line 116 — *(blank line)*  
Spacer.

Line 117 — `    function setVerifier(address verifier_) external onlyOwner {`  
Defines the setter for the verifier address.

Line 118 — `        if (verifier_ == address(0)) revert ZeroAddress();`  
Prevents setting a blank verifier.

Line 119 — `        verifier = verifier_;`  
Persists the new verifier address.

Line 120 — `    }`  
Ends `setVerifier`.

Line 121 — *(blank line)*  
Spacer.

Line 122 — `    function setDefaultCollateral(address collateral_) external onlyOwner {`  
Starts the function that swaps out the default collateral token.

Line 123 — `        if (allowlistPaused) revert AllowlistPaused();`  
Blocks the update if the allowlist is in a paused state.

Line 124 — `        if (!isCollateralAllowed[collateral_]) revert CollateralNotAllowed(collateral_);`  
Ensures the replacement token is already allowlisted.

Line 125 — `        defaultCollateral = collateral_;`  
Stores the new default collateral.

Line 126 — `        emit DefaultCollateralUpdated(collateral_);`  
Emits an event so off-chain systems know the new default token.

Line 127 — `    }`  
Closes `setDefaultCollateral`.

Line 128 — *(blank line)*  
Spacer.

Line 129 — `    function setCollateralStatus(address collateral, bool allowed) external onlyOwner {`  
Begins the function for toggling any collateral token’s allowlist status.

Line 130 — `        if (allowlistPaused) revert AllowlistPaused();`  
Prevents allowlist edits if the allowlist is globally paused.

Line 131 — `        if (!allowed && collateral == defaultCollateral) revert CannotDisableDefaultCollateral();`  
Blocks disabling whichever token is currently set as default.

Line 132 — `        isCollateralAllowed[collateral] = allowed;`  
Writes the new allowlist status to storage.

Line 133 — `        emit CollateralStatusUpdated(collateral, allowed);`  
Emits an event reflecting the update for watchers.

Line 134 — `    }`  
Ends `setCollateralStatus`.

Line 135 — *(blank line)*  
Spacer.

Line 136 — `    function setGuardian(address newGuardian) external onlyOwner {`  
Begins the function that changes the shared guardian address.

Line 137 — `        if (newGuardian == address(0)) revert ZeroAddress();`  
Ensures the guardian cannot be cleared.

Line 138 — `        guardian = newGuardian;`  
Stores the new guardian address.

Line 139 — `        emit GuardianUpdated(newGuardian);`  
Emits the guardian update event for visibility.

Line 140 — `    }`  
Closes `setGuardian`.

Line 141 — *(blank line)*  
Spacer ahead of the global control section.

Line 142 — `    // ───────────────────────────────`  
Divider comment introducing the “Global controls” section.

Line 143 — `    // Global controls`  
Section heading describing the next group of functions.

Line 144 — `    // ───────────────────────────────`  
Closing divider line.

Line 145 — `    function setAllowlistPaused(bool paused) external onlyGuardianOrOwner {`  
Opens the function to pause or resume the allowlist, callable by guardian or owner.

Line 146 — `        allowlistPaused = paused;`  
Persists the requested pause value.

Line 147 — `        emit AllowlistPauseSet(paused, msg.sender);`  
Emits an event showing the new status and caller.

Line 148 — `    }`  
Closes `setAllowlistPaused`.

Line 149 — *(blank line)*  
Spacer.

Line 150 — `    function setGlobalCommitPaused(bool paused) external onlyGuardianOrOwner {`  
Begins the global commit pause setter callable by guardian or owner.

Line 151 — `        globalCommitPaused = paused;`  
Stores the updated commit pause flag.

Line 152 — `        emit GlobalCommitPauseSet(paused, msg.sender);`  
Emits the associated event for market watchers.

Line 153 — `    }`  
Ends `setGlobalCommitPaused`.

Line 154 — *(blank line)*  
Spacer.

Line 155 — `    function setGlobalClaimPaused(bool paused) external onlyGuardianOrOwner {`  
Opens the global claim pause setter callable by guardian or owner.

Line 156 — `        globalClaimPaused = paused;`  
Stores the claim pause flag.

Line 157 — `        emit GlobalClaimPauseSet(paused, msg.sender);`  
Emits the event noting the new value and caller.

Line 158 — `    }`  
Closes `setGlobalClaimPaused`.

Line 159 — *(blank line)*  
Spacer ahead of per-market controls.

Line 160 — `    // ───────────────────────────────`  
Divider comment for the per-market section.

Line 161 — `    // Per-market controls`  
Heading describing that the following functions act on individual markets.

Line 162 — `    // ───────────────────────────────`  
Closing divider line.

Line 163 — `    function setMarketPauses(address market, bool commitPaused, bool claimPaused) external onlyGuardianOrOwner {`  
Starts the helper that lets guardian/owner pause/unpause a specific market.

Line 164 — `        if (!isMarket[market]) revert UnknownMarket();`  
Requires the target market to have been created by this factory.

Line 165 — `        RevealMarket(payable(market)).setCommitPaused(commitPaused);`  
Calls into the market to update its commit pause flag.

Line 166 — `        RevealMarket(payable(market)).setClaimPaused(claimPaused);`  
Calls into the market to update its claim pause flag.

Line 167 — `        emit MarketPaused(market, commitPaused, claimPaused, msg.sender);`  
Emits an event reporting the new pause states and caller.

Line 168 — `    }`  
Closes `setMarketPauses`.

Line 169 — *(blank line)*  
Spacer.

Line 170 — `    function setMarketGuardian(address market, address newGuardian) external onlyGuardianOrOwner {`  
Begins the helper that updates a specific market’s guardian.

Line 171 — `        if (!isMarket[market]) revert UnknownMarket();`  
Ensures the target is one of this factory’s markets.

Line 172 — `        RevealMarket(payable(market)).setGuardian(newGuardian);`  
Calls the market so it updates its guardian (the market will enforce non-zero guard).

Line 173 — `        emit MarketGuardianUpdated(market, newGuardian);`  
Emits an event reflecting the guardian change.

Line 174 — `    }`  
Ends `setMarketGuardian`.

Line 175 — *(blank line)*  
Spacer before the market creation section.

Line 176 — `    // ───────────────────────────────`  
Divider introducing the “Market creation” section.

Line 177 — `    // Market creation`  
Heading describing the next function.

Line 178 — `    // ───────────────────────────────`  
Closing divider line.

Line 179 — `    function createMarket(`  
Begins the main function that deploys a new RevealMarket clone.

Line 180 — `        string calldata eventId,`  
First parameter: the unique event identifier string.

Line 181 — `        uint256 commitDeadline,`  
Second parameter: commit cutoff timestamp for the market.

Line 182 — `        uint256 revealDeadline,`  
Third parameter: reveal cutoff timestamp.

Line 183 — `        address oracle,`  
Fourth parameter: oracle address authorized to post results.

Line 184 — `        address collateral,`  
Fifth parameter: optional collateral override (zero means use the default).

Line 185 — `        uint256 rakeBpsOverride`  
Sixth parameter: rake override in basis points (0 uses manager default).

Line 186 — `    ) external onlyOwner returns (address market) {`  
Closes the signature, marks it owner-only, and declares it returns the deployed market address.

Line 187 — `        if (oracle == address(0)) revert ZeroAddress();`  
Ensures the oracle pointer is provided.

Line 188 — `        if (commitDeadline <= block.timestamp || revealDeadline <= commitDeadline) revert InvalidDeadlines();`  
Checks that the deadlines are still in the future and in chronological order.

Line 189 — *(blank line)*  
Spacer before creation logic.

Line 190 — `        market = implementation.clone();`  
Creates a minimal proxy clone that points to the stored implementation.

Line 191 — `        address marketCollateral = collateral == address(0) ? defaultCollateral : collateral;`  
Uses the default collateral if none was provided; otherwise uses the supplied token.

Line 192 — `        if (!isCollateralAllowed[marketCollateral]) revert CollateralNotAllowed(marketCollateral);`  
Verifies the token that will be used is allowlisted.

Line 193 — `        if (rakeBpsOverride > IRakeManager(rakeManager).maxRakeBps()) revert InvalidRakeBps();`  
Ensures the override does not exceed the maximum allowed by the rake manager.

Line 194 — *(blank line)*  
Spacer before initialization call.

Line 195 — `        RevealMarket(payable(market)).initialize(`  
Calls the newly deployed market’s initializer.

Line 196 — `            eventId,`  
Passes along the event identifier.

Line 197 — `            commitDeadline,`  
Passes the commit deadline.

Line 198 — `            revealDeadline,`  
Passes the reveal deadline.

Line 199 — `            oracle,`  
Passes the oracle address.

Line 200 — `            verifier,`  
Injects the factory-wide verifier address.

Line 201 — `            rakeManager,`  
Supplies the shared rake manager pointer.

Line 202 — `            treasury,`  
Supplies the shared treasury address.

Line 203 — `            marketCollateral,`  
Supplies the resolved collateral token address.

Line 204 — `            guardian,`  
Passes the shared guardian as the market’s initial guardian.

Line 205 — `            rakeBpsOverride`  
Passes the override to let the market know its rake setting.

Line 206 — `        );`  
Closes the initializer call.

Line 207 — *(blank line)*  
Spacer before bookkeeping.

Line 208 — `        _markets.push(market);`  
Appends the new market address to the private list.

Line 209 — `        isMarket[market] = true;`  
Marks the address as a factory-created market for future checks.

Line 210 — *(blank line)*  
Spacer before the creation event emission.

Line 211 — `        emit MarketCreated(market, eventId, commitDeadline, revealDeadline, marketCollateral, rakeBpsOverride);`  
Emits the `MarketCreated` event with all relevant configuration details.

Line 212 — `    }`  
Closes `createMarket`.

Line 213 — *(blank line)*  
Spacer ahead of the view section.

Line 214 — `    // ───────────────────────────────`  
Divider comment for the view functions section.

Line 215 — `    // View functions`  
Heading describing the upcoming helper.

Line 216 — `    // ───────────────────────────────`  
Closing divider line.

Line 217 — `    function getMarkets() external view returns (address[] memory) {`  
Declares a read-only function that returns the list of created markets.

Line 218 — `        return _markets;`  
Returns the private `_markets` array copy.

Line 219 — `    }`  
Closes `getMarkets`.

Line 220 — *(blank line)*  
Spacer before helper section.

Line 221 — `    // ───────────────────────────────`  
Divider comment for internal helper section.

Line 222 — `    // Internal helpers`  
Heading introducing helper functions.

Line 223 — `    // ───────────────────────────────`  
Closing divider line.

Line 224 — `    function _onlyGuardianOrOwner() internal view {`  
Begins the shared authorization helper used by the modifier.

Line 225 — `        if (msg.sender != owner() && msg.sender != guardian) revert NotGuardianOrOwner();`  
Reverts unless the caller is either the owner or the guardian.

Line 226 — `    }`  
Closes `_onlyGuardianOrOwner`.

Line 227 — `}`  
Ends the contract definition.
