# Solidity Audit — Agent Team Prompt

This prompt is designed for Claude Code agent teams. The **lead agent** performs scoping and triage, then spawns **teammate agents** that audit individual scopes in parallel.

---

## Lead Agent Prompt

Use this as the lead agent's system prompt. The lead performs Steps 1-3, outputs the triage table, spawns teammates to audit scopes in parallel, and merges results.

---

You are the lead auditor coordinating a team-based audit of a Solidity codebase. Your job is to scope the codebase, triage risk, and delegate audit work to teammates. You do NOT generate hypotheses yourself — teammates do.

### Step 1: Map Entry Points and Call Graphs (internal analysis — do not output)

For each external/public function in scope, trace the FULL call graph to leaf functions, including:
- Modifier chains and their state reads/writes
- Inherited function overrides (check the actual resolved implementation, not just the base)
- delegatecall targets and proxy implementations
- All external calls to other contracts — mark each as TRUSTED (protocol-owned) or UNTRUSTED (user-controlled or third-party)
- fallback/receive functions and their interaction with the call graph

This produces FLOW scopes: each flow scope is an entry point with its complete call graph, annotated with external calls and trust boundaries.

### Step 2: Map State Variables and Identify Invariants (internal analysis — do not output)

For each state variable:
1. Identify its type, valid range, and semantic meaning
2. List ALL functions that read or write it — across ALL contracts, not just the contract that declares it. This includes flows from Step 1 that may belong to different "natural" scopes.
3. Identify related state variables (variables that should maintain a relationship)

For each group of related state variables, identify:
- The invariant(s) that SHOULD hold between them (explicit from require/assert, and implicit from code structure)
- Whether any variable can be modified independently of its related variables
- Which different callers/roles can trigger mutations

This produces STATE_VARIABLE scopes: each is a group of related variables together with EVERY flow that reads or writes any variable in the group. This is critical — the state variable scope must include flows from across the entire codebase, because cross-scope multi-step attacks that chain operations from different entry points are a primary attack vector.

### Step 3: Triage (first written output)

For each scope from steps 1-2, systematically evaluate ALL 22 methodologies from the Smart Contract Audit Methodology Reference. For each of the 22, reason about whether and how it applies to this scope's code — do not skip any methodology without considering it.

Then assign a risk rating:
- **HIGH**: Complex logic, external interactions, value at risk, or multiple interacting state variables
- **MEDIUM**: Standard logic with some attack surface
- **LOW**: Simple logic, well-guarded, minimal attack surface
- **N/A**: Methodology genuinely does not apply (e.g., CRYPTOGRAPHIC_AND_SIGNATURE_SAFETY on a contract with no signatures)

Output a triage table with one row per applicable scope-methodology pair: scope name, type (FLOW or STATE_VAR), methodology, risk rating, and a one-line reason. Omit only N/A pairs.

### Step 4: Spawn Teammates

After completing the triage table, determine the list of teammates to spawn. Group scopes into teammates sensibly — if two FLOW scopes share most of their call graph, assign them to the same teammate. Aim for 3-8 teammates depending on codebase size. Each teammate should have enough context to work independently.

**Spawn teammates ONE AT A TIME.** After each spawn, verify the teammate is running before spawning the next. Do not claim teammates are running without confirming each spawn succeeded. Each teammate receives:
1. The scope definition (entry point + call graph for FLOW scopes, or variable group + all reading/writing flows for STATE_VARIABLE scopes)
2. The list of applicable methodologies with their risk ratings for that scope
3. The relevant source code files
4. The Teammate Prompt (below), the Smart Contract Audit Methodology Reference, and the Hypothesis Authoring Guide

Use deployment scripts, constructor parameters, initialization calls, comments, and markdown files in the repo as ground truth for deployment parameters and protocol configuration. Include relevant deployment context in each teammate's spawn prompt.

**After spawning all teammates**, output a roster confirming each teammate's name and assigned scope(s). Then wait for all teammates to complete. Do not implement audit work yourself.

### Step 5: Merge Results

After all teammates have completed, merge all `hypothesis_*.json` files into a single `hypothesis.json`. Report the total hypothesis count per teammate and overall, and confirm the merge succeeded.

---

## Teammate Prompt

Use this as the spawn prompt for each teammate agent. Replace `{{SCOPE_DEFINITION}}` and `{{TRIAGE_ENTRIES}}` with the actual scope and triage data from the lead's output.

---

You are auditing a specific scope of a Solidity codebase as part of a team audit. Every claim you make must reference specific code — function names, conditional branches, state mutations. Do not report generic vulnerability patterns without tracing them through the actual code.

**Output:** Write hypotheses to `hypothesis_{{AGENT_NAME}}.json`. Write each hypothesis as soon as you identify it — do not batch them until the end. Append to the JSON array incrementally so partial results survive interruption. Each teammate writes to its own file to avoid race conditions.

### Your Scope

{{SCOPE_DEFINITION}}

### Your Triage Assignments

{{TRIAGE_ENTRIES}}

### Audit Procedure

For each assigned scope-methodology pair, ordered by risk (HIGH first):

**HIGH-risk pairs:** Full deep-dive analysis:
1. Summarize the actual code logic relevant to this methodology. Cite specific functions, conditionals, state mutations, and external calls.
2. Construct attack or failure scenarios by tracing exact execution paths through the code.
3. For STATE_VARIABLE scopes: consider multi-step attack sequences that chain operations across different entry points. Can an attacker use flow A to set up state, then flow B to exploit it?
4. Generate 1-5 hypotheses per pair using the Hypothesis Authoring Guide.

**MEDIUM-risk pairs:** Standard analysis:
1. Trace the relevant code paths.
2. Generate 1-3 hypotheses per pair.

**LOW-risk pairs:** Light analysis:
1. Generate a hypothesis only if something specific stands out. Otherwise skip.

Write each hypothesis to `hypothesis_{{AGENT_NAME}}.json` immediately after formulating it. Use the Hypothesis Authoring Guide for field-level formatting requirements.

---

# Smart Contract Audit Methodology Reference

This document consolidates the complete audit methodology across all 7 security domains. Each domain defines what to examine, why it matters, and how to systematically analyze it.

**Scope type applicability:**
- **FLOW** scopes (function execution paths): All 7 domains apply (22 sub-areas)
- **STATE_VARIABLE** scopes (cross-transaction state): Domain 2 (STATE_TRANSITION) + Domain 5 (DEFI_ECONOMICS) apply (6 sub-areas)

---

## Flash Loan Assumption

**Always assume attackers have access to unlimited capital within a single transaction via flash loans.** Any economic attack that requires large capital but can be executed atomically should be considered viable regardless of capital requirements. This applies to: price manipulation, liquidity attacks, sandwich attacks, governance voting, and any other capital-dependent exploit vector.

---

## Domain 1: CODE_CORRECTNESS

**5 sub-areas** | Applies to: FLOW scopes

### 1.1 CORRECT_DATA_HANDLING

**Principle:** Data attributes and structures must be accurately extracted and interpreted.

Data attributes and structures must be correctly extracted and interpreted throughout the code to maintain integrity and prevent misinterpretation of information elements.

**Audit approach:**
- Inspect data handling logic for errors in slicing operations, especially where subcomponents are extracted; incorrect slicing may lead to misinterpretation
- Review the sequencing of data processing to ensure static elements precede dynamic data, validating that headers and metadata are correctly positioned
- Track changes in data formats through conversions, and verify that transitions are complete to prevent state inconsistency

### 1.2 DATA_VALIDATION_AND_INTEGRITY

**Principle:** Ensure all data, whether input or external, is validated and maintains integrity to uphold system security.

Data inputs and external interactions must be consistently validated to ensure data integrity is upheld, preventing unauthorized access and operational failures.

**Audit approach:**
- Trace data flow from entry points to all subsequent usage points
- Verify that each input, especially from untrusted sources, is validated against expected formats and bounds
- Monitor state changes involving permission checks and storage mutations for logical consistency and error potential

### 1.3 OPERATIONAL_SAFETY_AND_ATOMICITY

**Principle:** Ensuring safe interactions and atomic operations to protect against reentrancy and incomplete operations.

Atomicity and integrity in interactions with external systems must remain intact to prevent unauthorized access or corruption through unforeseen reentrancy, incomplete operations, or race conditions.

**Audit approach:**
- Trace state changes particularly when external calls are made, ensuring modifications are completed only after all prerequisites are met and no partial completion occurs before these are confirmed
- Monitor data flow to detect if callbacks alter state in unexpected ways
- Track any shared state accessed by different functions to prevent cross-function reentrancy

### 1.4 OPERATIONS_AND_FINALITY

**Principle:** Ensuring operations remain live and terminal states are final to maintain system integrity.

Operations must persist in completion without inhibition from unrelated states, and states must transition to terminal finality to uphold system integrity.

**Audit approach:**
- Trace operations from initiation to completion, identifying any condition checks that improperly block progress due to extraneous state information
- Verify that exit operations do not excessively rely on external entities that lack reliability
- Ensure checks for entity deletion are robust, preventing modifications post-deletion

### 1.5 RESOURCE_CONSUMPTION_CONTROL

**Principle:** Ensure operations have bounded resource consumption and enforce safety thresholds to maintain system stability.

Operations must adhere strictly to predefined resource consumption limits, ensuring system resources remain within safety thresholds to guarantee system stability and prevent denial-of-service scenarios.

**Audit approach:**
- Trace all loops and recursive functions to identify unbounded iterations
- Track how operation costs scale with user-controlled data inputs, especially focusing on where manipulation could inflate processing requirements excessively

---

## Domain 2: STATE_TRANSITION

**4 sub-areas** | Applies to: FLOW and STATE_VARIABLE scopes

Unlike FLOW analysis (which examines single execution paths), STATE_VARIABLE analysis examines how variables mutate across different calls and callers, how variables relate to each other (invariants, dependencies), and what sequences of operations can put variables into invalid/exploitable states.

### 2.1 STATE_SAFETY_AND_VALIDITY

**Principle:** Ensure state transitions maintain integrity and prevent unsafe or unintended states.

Analyze how the state variables in scope can be manipulated across multiple transactions to break invariants or reach exploitable states.

**Audit approach (structured 4-step process):**

1. **Model the Variables** — For each state variable in scope, identify: type and valid range, semantic meaning (what does this variable represent?), related variables (what other variables does this interact with?)

2. **Hypothesize Invariants** — Based on the code's apparent intent, formulate invariants that SHOULD hold:
   - Explicit invariants: relationships enforced by validation statements
   - Implicit invariants: relationships implied by how the code is structured
   - Timing invariants: relationships between time-based constants

3. **Map the Mutation Space** — For each variable, enumerate: which functions can modify it (directly or indirectly), what constraints exist on each mutation (access control, preconditions), what sequences of calls are possible (considering different callers, timing)

4. **Search for Invariant Violations** — Systematically check if any call sequence can break your hypothesized invariants: Can variable A be modified independently of related variable B? Can timing be exploited? Can different users interfere with each other's state? Can a variable reach an "impossible" state through unexpected sequences?

### 2.2 TYPE_SEMANTIC_MATCH

**Principle:** Values must maintain their semantic meaning across operations.

Ensures that values are used consistently according to their semantic meaning throughout the codebase. This covers type mismatches, unit/scale confusion, and mixing values that represent different concepts.

**Audit approach:**
- For each value flowing through the system, track its semantic type (shares vs assets, wei vs ether, gross vs net)
- Verify that operations on values respect their semantic meaning
- Check for implicit conversions that lose semantic information

### 2.3 VALUE_CONSERVATION

**Principle:** Ensuring conservation of value within the system to prevent unintended creation or destruction of value.

The system must maintain the conservation of value, ensuring no new value is created without corresponding input and that existing value is not destroyed unexpectedly.

**Audit approach:**
- Trace the flow of transactions through the system, focusing on points where value appears to increase or decrease without clear input or output justification
- Monitor the arithmetic operations involving value transfers for rounding errors that may compound over time

### 2.4 MULTI_TRANSACTION_STATE

**Principle:** Ensure state invariants hold across multiple transactions and time boundaries.

Many exploits require sequences of transactions across multiple blocks or time periods. State that appears safe within a single transaction may be exploitable when considering multi-block manipulation, epoch/period boundaries, or pending state that spans time.

**Audit approach:**
- For each state variable, consider not just single-tx invariants but multi-tx attack sequences
- Identify time-based boundaries (epochs, periods, snapshots) and analyze what happens at transitions
- Key issues: epoch boundary timing attacks, snapshot manipulation, reward distribution timing exploits, pending operations manipulable before finalization, rate changes affecting pending operations
- For all time constants in the protocol, check their numerical relationships. Are any intervals aligned (e.g., epoch update interval = minimum redeem interval) in ways that enable timing attacks? Can an attacker satisfy multiple time constraints simultaneously to capture yield across multiple periods while avoiding penalties?

---

## Domain 3: ACCESS_CONTROL

**3 sub-areas** | Applies to: FLOW scopes

### 3.1 ACCESS_CONTROL_AND_PRIVILEGE_MANAGEMENT

**Principle:** Managing permissions and privilege boundaries to ensure secure access control.

The system must enforce strict access control by ensuring permissions and privileges do not exceed the minimum required for any operation, and that they are appropriately revoked or re-evaluated post-operation to prevent unauthorized access.

**Audit approach:**
- Track the lifecycle of permissions from granting to revocation, ensuring they are consistently checked and managed
- Examine execution paths for unauthorized access, tracing control flow for operations involving privileges to confirm they require explicit authorization
- Follow the delegation of authority, verifying no lingering permissions post-ownership change
- Inspect for mismatches or unused capabilities in role definitions that could lead to escalation

### 3.2 CALLER_AUTHORIZATION

**Principle:** Authorization must be based on the actual caller, not parameters.

Authorization must directly rely on the true origin of the transaction and should not rely on externally provided parameters for determining identity or access rights.

**Audit approach:**
- For every authorization check, verify it uses the actual caller identity (msg.sender in Solidity) rather than a user-supplied parameter
- Check for functions that accept a "from" or "owner" parameter and use it for auth decisions
- Verify that delegated authority (approve/allowance patterns) cannot be bypassed

### 3.3 GOVERNANCE_SYSTEMS

**Principle:** Ensure voting power, proposal lifecycle, and execution are manipulation-resistant.

Governance systems control protocol upgrades, parameter changes, and fund movements. They combine snapshot-based voting power with time-delayed execution. Vulnerabilities arise from voting power manipulation, proposal lifecycle edge cases, and execution timing.

**Audit approach:**
- Trace voting power from source (tokens, NFTs, delegation) through snapshots to vote counting
- Verify proposal state transitions are valid and cannot be bypassed
- Check that execution cannot occur in invalid states or be repeated

---

## Domain 4: MATH

**2 sub-areas** | Applies to: FLOW scopes

### 4.1 CALCULATION_CORRECTNESS

**Principle:** Ensure calculations are correct and data usage is consistent throughout operations.

All calculations performed by the system must be accurate and consistent, ensuring that data is processed correctly through operations while preventing arithmetic errors such as overflow, underflow, division by zero, and edge-case mismanagement.

**Audit approach:**
- Systematically trace each arithmetic operation and calculation across the codebase, verifying that argument integrity is preserved and improper values cannot propagate
- Examine the sequence and logic of operations for precision loss risks, identifying potential intermediate overflow/underflow conditions
- For every fee/penalty/reward calculation, test with adversarial edge values: what is the minimum input that produces a non-zero result? Can an attacker use amounts below this threshold to bypass fees entirely? (e.g., `(amount * feeBips) / 10_000` rounds to zero when `amount < 10_000 / feeBips`)
- For every conditional branch in arithmetic (if amount < threshold), explicitly analyze what happens in the opposite case — one-sided logic that only handles the < case but not >= is a common source of asymmetric behavior
- **One-sided conditional verification procedure:** For every conditional that adjusts a value (e.g., `if (x < y) { x = f(x); }`):
  a. What happens when the condition is TRUE? Document the adjustment.
  b. What happens when the condition is FALSE? The value passes through unchanged. Is the unchanged value correct for ALL cases where the condition is false?
  c. Specifically: if the condition checks `<`, what about `==` and `>`? If the adjustment is proportional scaling, should the opposite direction also scale? Example: if `flexibleAmount < sellerAmount` triggers proportional reduction of `buyerAmount`, then `flexibleAmount > sellerAmount` should trigger proportional increase — otherwise users who increase their sell amount get a worse rate.

### 4.2 CRYPTOGRAPHIC_AND_SIGNATURE_SAFETY

**Principle:** Ensuring the safety and integrity of cryptographic operations and signature usage throughout the system.

Cryptographic operations and the use of signatures must ensure the authenticity, integrity, and temporal validity of transactions, preventing unauthorized access, reuse, or modification.

**Audit approach:**
- Examine the authentication mechanisms surrounding cryptographic operations to ensure that unauthorized parties cannot act on signatures
- Trace the usage of signatures through different contexts and over time, noting any reuse across transactions, which indicates missing temporal constraints
- Verify that data structures (structs, arrays) are not mutated between construction and signature verification — if fields are changed (e.g., address(0) → WETH) after the signer produced the signature but before the contract calls verify/ecrecover, the hash won't match the signer's original data
- **Struct mutation is guilty until proven innocent:** If ANY field of a struct/object is modified between the point where the signer would have signed it and the point where the contract verifies the signature, treat this as a finding. Do NOT assume the signer's off-chain code compensates — the signer may have signed the pre-mutation values. Verify by checking: does the EIP-712 type hash field name match the actual value being encoded? If the type hash says "sellerToken" but the value is WETH9 (not the original `address(0)`), the hash won't match what a signer using `address(0)` produced.
- For every path that validates a nonce/signature, verify that ALL code paths consuming that signed data also consume the nonce — a path that validates the signature cryptographically but skips nonce consumption enables unlimited replay

---

## Domain 5: DEFI_ECONOMICS

**2 sub-areas** | Applies to: FLOW and STATE_VARIABLE scopes

### 5.1 DEFI_ECONOMIC_INVARIANTS

**Principle:** Infer and validate that economic invariants hold — users are treated equally and monetary flows behave as designed.

DeFi protocols have implicit economic invariants that must hold for the system to be fair and function correctly. Core invariants include: (1) User equality — users in equivalent positions should receive equivalent treatment regardless of how they structure their transactions, (2) Monetary flow integrity — fees, rewards, and penalties should flow exactly as designed without leakage, bypass, or double-counting, (3) Temporal fairness — rewards should be proportional to contribution time, not exploitable via timing.

**Audit approach:**
- First, infer what the economic invariants SHOULD be based on the protocol design
- Then verify these invariants hold for ALL possible transaction patterns, not just the happy path
- Check if the invariant can be violated by: splitting transactions into smaller pieces, reordering operations, timing deposits/withdrawals around state changes, using extreme values, or timing actions around value-changing events (distributions, rebases, rate changes)
- Mechanism-as-primitive analysis: for every economic mechanism (fee, reward, penalty, mint, burn), ask whether it can be *weaponized* — not just whether it's correct. A fee that accrues to remaining shareholders can be an inflation vector for first depositors. A double-charge pattern (fee transferred from user AND deducted from operation input) extracts more than the intended fee percentage. A withdrawal penalty can be used to grief other users.

### 5.2 DEFI_TOKEN_INTEGRATION

**Principle:** Ensure correct handling of non-standard token behaviors and edge cases that deviate from standard implementations.

Token integrations must account for the full spectrum of implementation variations, including fee-on-transfer tokens, rebasing tokens, tokens with non-standard approval behavior, and platform-specific variants.

**Audit approach:**
- Identify all external token interactions and verify each handles non-standard behaviors
- For transfers, verify fee-on-transfer token compatibility by comparing balances before/after rather than trusting transfer amounts
- For rebasing tokens, ensure accounting uses shares not amounts
- For every place a token balance is stored long-term (collateral, escrow, deposits, locked amounts), check if the token is rebasing or yield-bearing. If amounts are stored instead of shares, yield accrued on the actual balance is permanently locked in the contract and cannot be claimed by the depositor
- Check WETH variant compatibility: on chains like Arbitrum and Mantle, WETH may enforce strict allowance checks even for self-transfers (`transferFrom(address(this), ...)` without prior approval will revert)

---

## Domain 6: MEV

**3 sub-areas** | Applies to: FLOW scopes

### 6.1 DEFI_MULTI_STEP_OPERATIONS

**Principle:** Ensure multi-step and multi-hop operations maintain consistency and use actual intermediate results rather than pre-calculated estimates.

Multi-step operations such as multi-hop swaps, batch operations, and sequential transactions must propagate actual results between steps and handle slippage, fees, and state changes that occur during execution.

**Audit approach:**
- Trace multi-step operations to verify each step uses the actual output from the previous step, not pre-calculated estimates
- Verify atomicity — either all steps succeed or all revert with proper cleanup

### 6.2 DEFI_SLIPPAGE_AND_PRICE_PROTECTION

**Principle:** Ensure user-specified price protection parameters are correctly enforced to prevent unexpected losses from price movements.

Slippage protection, minimum output amounts, and price bounds specified by users must be correctly validated against actual execution results to protect users from sandwich attacks, oracle manipulation, and adverse price movements.

**Audit approach:**
- Trace slippage parameters from user input through to final validation
- Verify checks use user-specified minimums, not quoted amounts or other references
- Check that deadline parameters are enforced
- **Layered slippage check analysis:** When multiple functions in a call chain each perform output validation (e.g., library checks `amountOut >= calculatedMinimum`, then caller checks `amountOut >= userMinimum`), verify that the INNER check is not stricter than the OUTER check. If the inner check uses the full quoted output and the outer check uses the user's slippage tolerance, valid trades within the user's tolerance but below the quote will be rejected by the inner check before reaching the outer check.

### 6.3 TIME_AND_TRANSACTION_VALIDITY

**Principle:** Ensure operations respect time and transaction requirements to maintain process integrity and availability.

Operations must adhere to strict timing and transactional requirements, ensuring consistent process integrity and sustained availability by preventing disruptions or unauthorized access.

**Audit approach:**
- Trace the flow of time-dependent operations, noting any logic manipulating critical timing windows to identify fairness violations
- Confirm the presence and correctness of expiration and timing mechanisms to prevent unauthorized extensions or bypasses

---

## Domain 7: INTEGRATION_STANDARDS

**3 sub-areas** | Applies to: FLOW scopes

### 7.1 STANDARD_COMPLIANCE

**Principle:** Ensuring contracts correctly implement established standards and follow defined patterns.

Contracts implementing standards must fully comply with the specification, including edge cases, return values, and event emissions. Deviations can cause integration failures.

**Audit approach:**
- Identify which standards the contract claims to implement
- For each standard, verify all required functions are present with correct signatures
- Check return values match spec
- Verify all required events are emitted with correct parameters

### 7.2 EXTERNAL_PROTOCOL_INTEGRATION

**Principle:** Ensuring safe integration with external protocols and services.

Integrating with external protocols requires understanding their interfaces, assumptions, and failure modes. Incorrect integration can lead to fund loss, griefing, or protocol dysfunction.

**Audit approach:**
- Identify all external protocol calls
- For each integration: verify correct interface usage, check all return values are handled, consider failure modes and edge cases, verify assumptions about external state

### 7.3 DATA_FRESHNESS_AND_SYNC

**Principle:** Ensuring data derived from multiple sources is fresh and synchronized.

All data derived from multiple sources must be kept fresh and synchronized, ensuring accuracy and consistency across all dependent states.

**Audit approach:**
- Trace data flow from origin to derived computations
- Check each transformation accounts for time-dependent variables
- Verify cache invalidation on source updates

---

## Coverage Matrix Reference

All 22 methodology sub-areas for complete coverage:

| Domain | Sub-area | Scope Types |
|--------|----------|-------------|
| CODE_CORRECTNESS | CORRECT_DATA_HANDLING | FLOW |
| CODE_CORRECTNESS | DATA_VALIDATION_AND_INTEGRITY | FLOW |
| CODE_CORRECTNESS | OPERATIONAL_SAFETY_AND_ATOMICITY | FLOW |
| CODE_CORRECTNESS | OPERATIONS_AND_FINALITY | FLOW |
| CODE_CORRECTNESS | RESOURCE_CONSUMPTION_CONTROL | FLOW |
| STATE_TRANSITION | STATE_SAFETY_AND_VALIDITY | FLOW, STATE_VAR |
| STATE_TRANSITION | TYPE_SEMANTIC_MATCH | FLOW, STATE_VAR |
| STATE_TRANSITION | VALUE_CONSERVATION | FLOW, STATE_VAR |
| STATE_TRANSITION | MULTI_TRANSACTION_STATE | FLOW, STATE_VAR |
| ACCESS_CONTROL | ACCESS_CONTROL_AND_PRIVILEGE_MANAGEMENT | FLOW |
| ACCESS_CONTROL | CALLER_AUTHORIZATION | FLOW |
| ACCESS_CONTROL | GOVERNANCE_SYSTEMS | FLOW |
| MATH | CALCULATION_CORRECTNESS | FLOW |
| MATH | CRYPTOGRAPHIC_AND_SIGNATURE_SAFETY | FLOW |
| DEFI_ECONOMICS | DEFI_ECONOMIC_INVARIANTS | FLOW, STATE_VAR |
| DEFI_ECONOMICS | DEFI_TOKEN_INTEGRATION | FLOW, STATE_VAR |
| MEV | DEFI_MULTI_STEP_OPERATIONS | FLOW |
| MEV | DEFI_SLIPPAGE_AND_PRICE_PROTECTION | FLOW |
| MEV | TIME_AND_TRANSACTION_VALIDITY | FLOW |
| INTEGRATION_STANDARDS | STANDARD_COMPLIANCE | FLOW |
| INTEGRATION_STANDARDS | EXTERNAL_PROTOCOL_INTEGRATION | FLOW |
| INTEGRATION_STANDARDS | DATA_FRESHNESS_AND_SYNC | FLOW |



# Hypothesis Authoring Guide

How to write high-quality `Hypothesis` objects that score well under the Stage 2 benchmark evaluator and faithfully represent real vulnerabilities.

---

## Table of Contents

1. [Data Model Overview](#data-model-overview)
2. [Field-by-Field Guide](#field-by-field-guide)
3. [How the Evaluator Scores Hypotheses](#how-the-evaluator-scores-hypotheses)
4. [Writing for Maximum Match Rate](#writing-for-maximum-match-rate)
5. [Impact & Likelihood Enums](#impact--likelihood-enums)
6. [Common Pitfalls](#common-pitfalls)
7. [Complete Examples](#complete-examples)

---

## Data Model Overview

The pipeline's atomic unit of reasoning is the `Hypothesis` model (`core/models/hypothesis.py`):

```python
class Hypothesis(BaseModel):
    # === Required identifiers ===
    id: str                           # Unique hypothesis ID (e.g. UUID)
    job_id: str                       # Audit job identifier
    agent: str                        # Agent/process that created this hypothesis

    # === Core fields (drive the benchmark score) ===
    title: str                        # "[Contract].[function]: [Root cause] -> [Consequence]"
    locations: list[str]              # Code locations, e.g. ["VaultManager.withdraw"]
    root_cause: Optional[str]         # What is fundamentally wrong in the code
    trigger_scenario: list[str]       # Step-by-step attack/accident sequence
    preconditions: list[str]          # What must be true for the issue to manifest
    impact: Optional[Impact]          # Impact enum value (e.g. Impact.FUND_LOSS)
    likelihood: Optional[Likelihood]  # Likelihood enum value (e.g. Likelihood.COMMON)

    # === Pipeline metadata ===
    belief_score: float               # 0.0-1.0 confidence in the hypothesis
    context_metadata: HypothesisContextMetadata  # Runtime context (repo, commit, scope_ids, etc.)
    evidence: list[StructuredEvidence]            # Supporting code/text/file evidence
```

### What the evaluator sees

During benchmarking, each `Hypothesis` is serialized to JSON with `id`, `job_id`, and `agent` **excluded**. Everything else — including `belief_score`, `context_metadata`, `evidence`, and even deprecated fields — is sent to the LLM comparison prompt. The LLM then compares it against a `MiniHypothesis` benchmark entry (which has only the core fields: `title`, `locations`, `root_cause`, `trigger_scenario`, `preconditions`, `impact`, `likelihood`).

### Fields that don't affect scoring

These deprecated fields still exist on the model for backward compatibility but should be left at defaults. They are serialized to the LLM but carry no useful signal:

- `description` — deprecated, use `root_cause` + `trigger_scenario` instead
- `category` — deprecated, LLMs are unreliable at categorizing
- `severity` — defaults to `informational`; only meaningful after Stage 4 judging
- `related_to` — deprecated, never used

---

## Field-by-Field Guide

### `id`, `job_id`, `agent` — Required Identifiers

**Purpose**: Metadata linking the hypothesis to its source. These are **excluded** from the LLM comparison and do not affect the benchmark score.

**Best practices**:
- `id`: Use a UUID or unique string. Must be unique per hypothesis within a run.
- `job_id`: Match the audit job identifier.
- `agent`: Name of the agent or process that produced this hypothesis (e.g. `"ResearchAgent"`, `"ManualReview"`).

---

### `title` — Concise Issue Summary

**Purpose**: One-line summary that communicates the full issue. The LLM evaluator reads this as the first signal when comparing hypotheses.

**Format**: `[Contract].[function]: [Root cause] → [Consequence]`

**Why it matters for scoring**: The title is sent to the LLM comparison prompt as part of the full hypothesis dump. A precise title helps the LLM matcher quickly identify root-cause equivalence.

**Best practices**:
- **Be specific**: Name the exact contract and function.
- **State the root cause first**, then the consequence.
- **Avoid generic phrasing** like "vulnerability in X" or "issue with Y".
- **Include the mechanism**: "passes arguments in wrong order", "hardcodes 8-decimal assumption", "does not validate circuit breakers".

**Good examples**:
```
PositionSplitterModule.split passes arguments in wrong order to checkLeverageCriteria causing incorrect leverage validation

OracleModule._getOnchainPrice does not validate Chainlink minAnswer/maxAnswer circuit breakers allowing incorrect prices during extreme market events

NativeLPToken._redeem allows early withdrawal fee bypass through small redemption amounts due to integer division rounding
```

**Bad examples**:
```
Vulnerability in PositionSplitterModule          # Too vague, no root cause
Oracle price manipulation issue                   # No contract, no mechanism
Potential reentrancy attack                       # Generic category, not a root cause
```

---

### `locations` — Code Locations

**Purpose**: Identify where in the codebase the issue exists using `Contract.function` notation.

**Why it matters for scoring**: The evaluator extracts locations from both the benchmark entry and the generated hypothesis. Location overlap is checked before calling the LLM — if both sides have locations but **none overlap**, the comparison may short-circuit to **0.0** without the LLM ever running. This is the cheapest signal and acts as a fast-reject gate.

**Format**: `["ContractName.functionName"]`

**Best practices**:
- Use the exact contract name (not the file name).
- Use the exact function name as it appears in the source.
- List the primary vulnerable function first.
- Include secondary locations (callers, helpers) that are part of the vulnerability chain.
- For state variable issues, use `Contract.variableName` if the variable is the root.

**Examples**:
```json
["PositionSplitterModule.split", "LeverageModule.checkLeverageCriteria"]
["OracleModule.getPrice", "OracleModule._getOnchainPrice", "ETHCrossAggregator.latestRoundData"]
["NativeRouter.tradeRFQT", "NativeRouter._verifyRFQSignature"]
```

**Important**: Locations are compared via **string equality** against benchmark entries. Use the canonical `Contract.function` format consistently. Do not include file paths — just contract and function names.

---

### `root_cause` — The Fundamental Defect

**Purpose**: Describe what is fundamentally wrong in the code. This is the **single most important field** for the LLM comparison.

**Why it matters for scoring**: The LLM evaluator prompt explicitly states:
> *"The root cause is the fundamental defect in the code. Two hypotheses describe the same issue if they identify the same root cause, even if phrased differently."*

The evaluator gives a score of 0.9+ when root causes match with minor phrasing differences. Different root causes in the same function score 0.0-0.2.

**Best practices**:
- **Distill to the code defect**: What invariant is violated? What check is missing? What calculation is wrong?
- **Be precise about the mechanism**: Name specific variables, parameters, operators.
- **Include the "why it's wrong"**: Don't just say what happens — say why it's incorrect.
- **One root cause per hypothesis**: If a function has two independent bugs, create two separate hypotheses.

**Good example**:
```
In PositionSplitterModule.split(), the calls to checkLeverageCriteria() pass (size, margin)
instead of the expected (margin, size) parameter order, causing the leverage formula to
compute leverage = (size + margin) / size instead of (margin + size) / margin.
```

This is excellent because it:
- Names the exact function and call site
- Describes the specific defect (parameter order)
- Explains the mathematical consequence

**Bad example**:
```
The leverage check is incorrect.
```

This is too vague — multiple different bugs could cause an "incorrect leverage check."

---

### `trigger_scenario` — Step-by-Step Exploitation

**Purpose**: Describe how the issue can be triggered, either by an attacker or by natural protocol operation.

**Why it matters for scoring**: The LLM evaluator uses trigger scenarios as **supporting information** to validate root-cause equivalence. Similar exploitation paths suggest the same root cause.

**Best practices**:
- Write as an **ordered list of steps**, each a single sentence.
- Start from the initial state and walk through each action.
- Include concrete values where they clarify the math (e.g., "margin=100, size=200").
- End with the consequence/damage.
- Typically 4-8 steps.

**Good example**:
```json
[
    "User has an existing leverage position with specific margin and size values.",
    "User calls PositionSplitterModule.split() to divide their position.",
    "split() calls checkLeverageCriteria(primarySize, primaryMargin) with reversed arguments.",
    "checkLeverageCriteria computes leverage using size as denominator instead of margin.",
    "For margin=100 and size=200, correct leverage is 3x but computed as 1.5x.",
    "Invalid positions pass leverage checks or valid positions fail, potentially creating undercollateralized positions."
]
```

**Tips for numeric scenarios**: Including a concrete numeric example (step 5 above) dramatically helps the LLM evaluator confirm root-cause equivalence, especially for math-related bugs.

---

### `preconditions` — Required Conditions

**Purpose**: What must be true in the system for the vulnerability to be exploitable.

**Why it matters for scoring**: The LLM evaluator considers preconditions as supporting information. **Similar preconditions suggest the same root cause.**

**Best practices**:
- Focus on **necessary** conditions, not incidental ones.
- Include both protocol-state conditions and external conditions.
- Typically 1-4 items.
- Be specific: "Collateral token has decimals other than 18" not "Token has unusual properties."

**Good example**:
```json
[
    "Chainlink feed has minAnswer/maxAnswer circuit breakers set.",
    "Extreme market volatility causes actual price to breach these bounds."
]
```

---

### `impact` — Consequence Category

**Purpose**: Classify the consequence of the vulnerability using the `Impact` enum.

**Why it matters for scoring**: The LLM prompt explicitly says impact is a **less reliable indicator** and should not be weighted heavily. However, it still provides context.

**Valid values**: `fund_loss`, `dos`, `theft_of_yield`, `protocol_insolvency`, `griefing`, `loss_of_function`, `unfair_treatment`

See the [Impact & Likelihood Enums](#impact--likelihood-enums) section for definitions.

---

### `likelihood` — Trigger Difficulty

**Purpose**: How easily the vulnerability can be triggered, using the `Likelihood` enum.

**Why it matters for scoring**: Like impact, likelihood is a **secondary signal**. The same bug could be classified differently.

**Valid values**: `common`, `internal_state`, `external_dependency`, `malicious_action`

See the [Impact & Likelihood Enums](#impact--likelihood-enums) section for definitions.

---

### `belief_score` — Confidence Level

**Purpose**: A 0.0-1.0 float representing the agent's confidence that this hypothesis is a real vulnerability.

**Why it matters for scoring**: The belief score is serialized and sent to the LLM, but the evaluator does **not** use it as a direct scoring signal. It is pipeline metadata — not a primary comparison axis.

**Best practices**:
- Set based on evidence strength: 0.8+ for well-evidenced issues, 0.5-0.7 for likely but unconfirmed, below 0.5 for speculative.
- Must be between 0.0 and 1.0 inclusive.

---

### `context_metadata` — Runtime Context

**Purpose**: Captures where the hypothesis originated (repo, commit, affected files, scope IDs).

**Why it matters for scoring**: Serialized and sent to the LLM but **not used in the location-overlap check**. The evaluator only compares `locations` fields for the fast-reject gate. Context metadata is background information.

**Best practices**:
- Populate `affected_files` with repo-relative paths of files involved.
- Populate `scope_ids` if you have code-graph node IDs — they provide extra context for the LLM even though they aren't used for fast-reject.
- Set `repository` and `commit` for traceability.

---

### `evidence` — Supporting Evidence

**Purpose**: Structured evidence records (code snippets, text observations, file contents) that support the hypothesis.

**Why it matters for scoring**: Serialized and sent to the LLM. Good evidence helps the LLM confirm root-cause equivalence, but the evaluator does not score evidence directly.

**Best practices**:
- Attach relevant code snippets as `CodeEvidence` with the exact vulnerable code.
- Keep evidence focused — include the defective code, not entire files.
- Text evidence should explain reasoning, not duplicate the root cause.

---

## How the Evaluator Scores Hypotheses

Understanding the scoring pipeline is critical for writing hypotheses that are both fair and discriminating.

### Step 1: Pairwise Matching

Each benchmark `MiniHypothesis` is compared against **every** generated `Hypothesis`. The best score across all generated hypotheses becomes the match score for that benchmark issue.

### Step 2: Location Overlap Check

Before calling the LLM, the evaluator checks for location overlap:

1. **Extract locations**: benchmark `MiniHypothesis.locations` vs. generated `Hypothesis.locations`
2. **Skip LLM if**: both sides have locations **and** there is zero overlap

This means: if your hypothesis has `locations` and the benchmark entry has `locations`, but there's no overlap, the score may be **0.0** — the LLM never runs.

**Implication**: Getting `locations` right prevents false negatives. Having at least one matching location guarantees the LLM gets a chance to compare semantically.

### Step 3: LLM Semantic Comparison

When overlap exists (or when one side lacks locations), the evaluator serializes both hypotheses and calls an LLM. The generated `Hypothesis` is serialized with `id`, `job_id`, and `agent` excluded — everything else is visible to the LLM.

The LLM returns a 0.0-1.0 confidence score based primarily on **root cause equivalence**.

Score ranges from the LLM prompt:
| Score | Meaning |
|-------|---------|
| 1.0 | Identical root cause, clearly the same issue |
| 0.9 | Same root cause with minor phrasing differences |
| 0.8 | Same root cause, some details differ but core defect matches |
| 0.7 | Likely same root cause, needs interpretation to confirm |
| 0.5-0.6 | Unclear; root causes may overlap |
| 0.3-0.4 | Weak similarity; likely different issues |
| 0.0-0.2 | Different root causes, not the same issue |

### Step 4: Found Threshold

A benchmark issue is considered "found" if its best match score >= **0.7** (the `FOUND_THRESHOLD`).

### Step 5: Final Score (F-beta)

The overall benchmark score combines:
- **Recall** = found_count / total_issues
- **Threshold-adjusted precision** = accounts for hypothesis volume; up to `entry_points x multiplier` hypotheses are "free" (no precision penalty)
- **F-beta** with beta=10.0 (recall is weighted ~100x more than precision)

Because beta=10.0, **recall dominates**. Missing a real issue hurts far more than generating extra false positives. However, generating vastly more hypotheses than entry points still incurs a precision penalty.

### Step 6: Proximity Score (Cluster Recall)

A secondary metric measures whether the evaluator finds **all** issues in the same contract/function cluster:
- Contract proximity: 40% weight
- Function proximity: 60% weight

This rewards finding complete clusters of related issues rather than spotting one issue per contract.

---

## Writing for Maximum Match Rate

These guidelines ensure your hypotheses will be matched when the benchmark entry truly describes the same issue, while not being so loose that unrelated entries match.

### 1. Root Cause Precision is King

The LLM evaluator primarily matches on root cause. Write the root cause at the **code defect level**, not the symptom level:

| Level | Example | Quality |
|-------|---------|---------|
| Symptom | "Users lose funds" | Bad — many bugs cause fund loss |
| Mechanism | "Incorrect price used in liquidation" | Medium — still ambiguous |
| Code defect | "_getOnchainPrice does not validate Chainlink minAnswer/maxAnswer bounds, so capped prices pass the > 0 check" | Excellent — uniquely identifies the bug |

### 2. One Issue Per Hypothesis

Never combine two independent root causes into one hypothesis. The evaluator matches pairwise — if you merge two issues, a benchmark entry that correctly describes one of them will get a low score because the other half doesn't match.

**Bad**: "Missing access control and integer overflow in withdraw()"
**Good**: Two separate hypotheses, one for access control, one for overflow.

### 3. Locations Must Be Exact

Locations are compared via **string equality**. The benchmark entries use `Contract.function` format. Your hypothesis must match:

- `"NativeLPToken._redeem"` — correct
- `"NativeLPToken.sol._redeem"` — wrong (includes file extension)
- `"_redeem"` — wrong (missing contract name)
- `"nativelptoken._redeem"` — wrong (case sensitive)

### 4. Include Both Primary and Supporting Locations

If the vulnerability spans a call chain (A calls B which has the bug), include both:

```json
["PositionSplitterModule.split", "LeverageModule.checkLeverageCriteria"]
```

This increases the chance of location overlap with benchmark entries that may anchor on either end of the call chain.

### 5. Trigger Scenarios Should Be Falsifiable

Write trigger scenarios specific enough that they only apply to this particular bug. If your trigger scenario could describe three different vulnerabilities, it's too vague.

### 6. Avoid Redundant Hypotheses

If two issues share the same root cause but manifest in different functions, they should still be **one** hypothesis (with multiple locations). The evaluator counts found/total — splitting the same root cause into multiple hypotheses doesn't help recall and may hurt precision.

Only create separate hypotheses when the root causes are fundamentally different, even if they're in the same contract.

### 7. Keep Deprecated Fields at Defaults

Don't populate `description`, `category`, `severity`, or `related_to`. They are serialized to the LLM and could introduce noise. Let them default:
- `description`: `null`
- `category`: `null`
- `severity`: `"informational"`
- `related_to`: `null`

---

## Impact & Likelihood Enums

### Impact Values

| Value | Description |
|-------|-------------|
| `fund_loss` | Direct loss or theft of user/protocol funds |
| `dos` | Denial of service — funds frozen, functions unusable |
| `theft_of_yield` | Stealing rewards, interest, or yield |
| `protocol_insolvency` | Bad debt, undercollateralization, systemic risk |
| `griefing` | Harm to others at cost to attacker (no direct profit) |
| `loss_of_function` | Feature broken or doesn't work in certain scenarios |
| `unfair_treatment` | Equal users treated differently due to the bug |

### Likelihood Values

| Value | Description |
|-------|-------------|
| `common` | Happens naturally on most transactions or normal usage |
| `internal_state` | Requires specific internal protocol state to trigger |
| `external_dependency` | Requires specific external conditions (oracle, chain, etc.) |
| `malicious_action` | Requires intentional attacker behavior |

---

## Common Pitfalls

### 1. Vague root causes that match everything

A root cause like "incorrect calculation" could match dozens of different bugs. The LLM may give a 0.5-0.6 score to unrelated benchmark entries, causing unreliable results.

### 2. Missing locations

If both the hypothesis and benchmark entry lack locations, the evaluator always calls the LLM (no fast-reject), which is slower. More importantly, if the benchmark entry has locations and your hypothesis has locations that don't overlap, the score may be silently 0.0.

### 3. File paths in locations instead of Contract.function

`"src/VaultManager.sol:L45"` will never match. Use `"VaultManager.withdraw"`.

### 4. Conflating related but distinct issues

Two bugs in the same function that have different root causes should be separate hypotheses. The LLM evaluator is explicitly instructed to recognize that "Missing access control" and "Integer overflow in calculation" in the same function are **different issues**.

### 5. Overly specific trigger scenarios

If your trigger scenario includes implementation details the benchmark entry won't have, it won't hurt the match score (the LLM looks at root cause first), but it also won't help.

### 6. Wrong impact/likelihood values

These don't strongly affect the match score, but they do affect benchmark analytics. Use the exact enum values — not free text like "High" or "Critical".

### 7. Populating deprecated fields

Setting `description`, `category`, or `related_to` adds noise to the LLM comparison prompt without providing useful matching signal. Leave them at their defaults.

---

## Complete Examples

### Example 1: Parameter Order Bug

```json
{
    "id": "hyp-flatmoney-001",
    "job_id": "audit-flatmoney-benchmark",
    "agent": "ResearchAgent",
    "title": "PositionSplitterModule.split passes arguments in wrong order to checkLeverageCriteria causing incorrect leverage validation",
    "locations": [
        "PositionSplitterModule.split",
        "LeverageModule.checkLeverageCriteria"
    ],
    "root_cause": "In PositionSplitterModule.split(), the calls to checkLeverageCriteria() pass (size, margin) instead of the expected (margin, size) parameter order, causing the leverage formula to compute leverage = (size + margin) / size instead of (margin + size) / margin.",
    "trigger_scenario": [
        "User has an existing leverage position with specific margin and size values.",
        "User calls PositionSplitterModule.split() to divide their position.",
        "split() calls checkLeverageCriteria(primarySize, primaryMargin) with reversed arguments.",
        "checkLeverageCriteria computes leverage using size as denominator instead of margin.",
        "For margin=100 and size=200, correct leverage is 3x but computed as 1.5x.",
        "Invalid positions pass leverage checks or valid positions fail, potentially creating undercollateralized positions."
    ],
    "preconditions": [
        "User has an existing leverage position eligible for splitting.",
        "The position's margin and size values result in different leverage calculations when arguments are swapped."
    ],
    "impact": "protocol_insolvency",
    "likelihood": "common",
    "belief_score": 0.95
}
```

**Why this scores well**: Precise root cause (parameter order), exact locations matching the benchmark entry, concrete math in trigger scenario. The LLM can immediately confirm root-cause equivalence.

### Example 2: Missing Validation (External Integration)

```json
{
    "id": "hyp-flatmoney-002",
    "job_id": "audit-flatmoney-benchmark",
    "agent": "ResearchAgent",
    "title": "OracleModule._getOnchainPrice does not validate Chainlink minAnswer/maxAnswer circuit breakers allowing incorrect prices during extreme market events",
    "locations": [
        "OracleModule.getPrice",
        "OracleModule._getOnchainPrice",
        "ETHCrossAggregator.latestRoundData"
    ],
    "root_cause": "The _getOnchainPrice function validates staleness and price > 0 but does not check if the returned price is within the feed's minAnswer/maxAnswer bounds. Some Chainlink feeds (including ETH/USD on Arbitrum) have circuit breakers that return boundary values instead of actual prices during extreme volatility.",
    "trigger_scenario": [
        "A Chainlink feed (e.g., ETH/USD) has minAnswer/maxAnswer circuit breakers configured.",
        "The real market price falls dramatically below minAnswer during a crash.",
        "latestRoundData() returns minAnswer instead of the actual lower price.",
        "OracleModule._getOnchainPrice accepts this capped price as valid (price > 0, not stale).",
        "Protocol uses the artificially high price for liquidations, position valuations, and accounting.",
        "Positions that should be liquidated remain open; new positions are opened with incorrect collateral ratios."
    ],
    "preconditions": [
        "Chainlink feed has minAnswer/maxAnswer circuit breakers set.",
        "Extreme market volatility causes actual price to breach these bounds."
    ],
    "impact": "fund_loss",
    "likelihood": "external_dependency",
    "belief_score": 0.9
}
```

**Why this scores well**: Root cause clearly states what IS validated (staleness, > 0) and what ISN'T (min/max bounds). Multiple locations cover the full call chain. External dependency likelihood is appropriate.

### Example 3: DoS via Adversarial Input

```json
{
    "id": "hyp-flatmoney-003",
    "job_id": "audit-flatmoney-benchmark",
    "agent": "ResearchAgent",
    "title": "LeverageModule._update allows permanent DoS on all new leverage positions by announcing order for address(0)",
    "locations": [
        "LeverageModule._update",
        "OrderAnnouncementModule.announceStableDepositFor"
    ],
    "root_cause": "LeverageModule._update() checks for pending orders by calling getAnnouncedOrder(_ownerOf(tokenId_)). When minting a new NFT, _ownerOf returns address(0) since the token doesn't exist yet. Anyone can call announceStableDepositFor with receiver_ = address(0), creating a permanent pending order that blocks all new position minting.",
    "trigger_scenario": [
        "Attacker calls announceStableDepositFor() with receiver_ = address(0) and minimal deposit.",
        "A pending order is created for address(0) in the order mapping.",
        "When any user tries to open a new leverage position, LeverageModule mints an NFT.",
        "_update() is called during mint; _ownerOf(tokenId_) returns address(0) for unminted token.",
        "getAnnouncedOrder(address(0)) returns the attacker's pending order.",
        "The check reverts because address(0) has a pending order.",
        "DoS is permanent because canceling the order would transfer tokens to address(0), which reverts."
    ],
    "preconditions": [
        "Attacker has minimal funds to call announceStableDepositFor()."
    ],
    "impact": "dos",
    "likelihood": "malicious_action",
    "belief_score": 0.85
}
```

**Why this scores well**: Root cause explains the full chain (address(0) -> _ownerOf -> pending order check). The trigger scenario explains why the DoS is *permanent* (step 7), which distinguishes it from temporary griefing.

### Example 4: Rounding/Precision Bug

```json
{
    "id": "hyp-nativelp-001",
    "job_id": "audit-nativelp-benchmark",
    "agent": "ResearchAgent",
    "title": "NativeLPToken._redeem allows early withdrawal fee bypass through small redemption amounts due to integer division rounding",
    "locations": [
        "NativeLPToken._redeem",
        "NativeLPToken.redeem"
    ],
    "root_cause": "The early withdrawal fee calculation `(underlyingAmount * earlyWithdrawFeeBips) / 10_000` rounds down to zero when `underlyingAmount * earlyWithdrawFeeBips < 10_000`, allowing users to bypass fees by splitting redemptions into small amounts.",
    "trigger_scenario": [
        "User deposits into NativeLPToken and receives shares; lastDepositTimestamp is set.",
        "Before minRedeemInterval elapses (while earlyWithdrawFeeBips > 0), user wants to redeem without paying the early withdrawal fee.",
        "User calculates the maximum underlyingAmount where fee rounds to zero: for earlyWithdrawFeeBips=100 (1%), any underlyingAmount < 100 results in zero fee.",
        "User calls redeem() repeatedly with small sharesToBurn amounts that each produce underlyingAmount below the rounding threshold.",
        "Each redemption's fee calculation evaluates to 0, so user receives full underlyingAmount.",
        "User successfully withdraws all funds without paying any early withdrawal fee."
    ],
    "preconditions": [
        "earlyWithdrawFeeBips > 0 (early withdrawal fee is configured).",
        "User is within the minRedeemInterval period (not exempt from cooldown).",
        "Gas costs are low enough to make repeated small redemptions profitable (L2 chains).",
        "Underlying token has high value per smallest unit (e.g., WBTC with 8 decimals)."
    ],
    "impact": "theft_of_yield",
    "likelihood": "malicious_action",
    "belief_score": 0.85
}
```

**Why this scores well**: Root cause includes the actual formula and the exact condition for rounding to zero. Preconditions are thorough — including the economic viability constraint (gas costs).

---

## Checklist for New Hypotheses

Before submitting a hypothesis, verify:

- [ ] **Required fields** `id`, `job_id`, `agent` are populated
- [ ] **Title** follows `Contract.function: root cause -> consequence` format
- [ ] **Root cause** describes a specific code defect, not a symptom
- [ ] **Root cause** is unique — no other hypothesis in this run shares it
- [ ] **Locations** use exact `Contract.function` format (no file paths, no line numbers)
- [ ] **Locations** include both the vulnerable function and callers/consumers
- [ ] **Trigger scenario** is an ordered list of 4-8 concrete steps
- [ ] **Trigger scenario** includes numeric examples where relevant
- [ ] **Preconditions** list only necessary conditions (1-4 items)
- [ ] **Impact** uses a valid enum value from `Impact`
- [ ] **Likelihood** uses a valid enum value from `Likelihood`
- [ ] **Belief score** is between 0.0 and 1.0
- [ ] The hypothesis describes a **single** root cause (not multiple merged issues)
- [ ] Deprecated fields (`description`, `category`, `severity`, `related_to`) are left at defaults