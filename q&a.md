# Reveal Market Marketing Q&A

1) In one paragraph, what is Reveal Market and what unfair dynamics in prediction markets are you trying to fix?

Reveal Market is a full-stack, zero-knowledge prediction market platform: FastAPI API + ingestion worker + Next.js frontend + relayer + hedger + Groth16-verified contracts. It is built to stop the most corrosive unfair dynamic in prediction markets: live transparency that turns trading into a public signaling contest. When odds, orderflow, and positions are visible, whales can intimidate, copy traders can free-ride, MEV bots can extract, and smaller participants get pushed into reacting rather than reasoning. Reveal Market removes that pressure by keeping live activity private and revealing only the final outcome and a verifiable proof that the settlement math is correct.

2) Your core claim is bold: "no odds, orderflow, or positions visible while live." What does that change for a trader's experience compared to Polymarket style markets?

It turns the live market from a social price-action arena into a conviction-based experience. On Polymarket-style markets, you watch the odds tick and the orderflow roll, then you decide whether to follow, fade, or front-run. On Reveal Market, there is nothing to chase. You commit based on your view of the event, not a visible crowd signal. That changes the psychology: less panic, less herd behavior, and fewer incentives to game perception rather than seek truth.

3) If odds aren't visible during the live market, how do participants decide what to do? What information is available while a market is active?

Participants act on the same ingredients that make prediction markets valuable in the first place: the event, the rules, and their own information edge. While active, the market presents the title/description, outcome options, deadlines, fixed ticket size, and any applicable caps. The stack also supports live FX data so users understand stake value in real terms without broadcasting market odds. The decision is deliberate: "Do I believe this outcome enough to commit a ticket?" not "Can I read the tape faster than everyone else?"

4) What problems does hidden orderflow/positions solve specifically copy trading, whale intimidation, market manipulation, MEV, signaling games, something else?

It directly targets all of those. Hidden flow removes copy trading because there is nothing to mirror in real time. It neutralizes whale intimidation because no one can flaunt size to scare smaller traders. It blunts manipulation and signaling games that rely on visible pressure. And it strips away a common MEV surface, because there is no public orderflow or live price movement to exploit. In short, it makes the market about information, not intimidation.

5) Let's talk pricing: what mechanism determines the eventual payouts and how does the system maintain economic correctness without exposing live odds?

Payouts are determined by fixed-ticket commitments and deterministic on-chain settlement. The API issues signed quotes with caps, users commit fixed tickets, and those commitments are hashed (Poseidon) and batched. After resolution, the protocol computes payouts from the pool state according to the outcome. Economic correctness is not a promise; it is enforced by on-chain rules and backed by a verifiable proof that the settlement math was executed exactly as specified.

6) After resolution, you generate a verifiable proof of correct pool math and payouts. What exactly is being proven, and who verifies it?

The proof shows that the settlement math was executed correctly over the committed pool state: batch roots, ticket hashes, and outcome logic produce the exact payouts users receive. It also enforces that the correct circuit hash was used. The on-chain verifier contract checks the proof so settlement is cryptographically guaranteed, and off-chain services can independently verify it for monitoring and auditability.

7) What's the trade off? What did you have to give up (speed, UX simplicity, composability, liquidity efficiency) to achieve full live-market privacy?

The biggest trade-off is giving up live odds UX and some of the instant price-discovery feel that traders are used to. The system is also more complex: commit-reveal, proof generation, and batch settlement are heavier than a visible order book. You trade simplicity and immediate feedback for privacy, integrity, and a market that is harder to game.

8) What's the hardest technical challenge you've faced so far, and what was the breakthrough that made you confident the design could work?

The hardest challenge is proving batched settlement correctness at production scale without sacrificing determinism or auditability. The breakthrough was a rigorous, end-to-end proof pipeline: fixed batch size (256), Poseidon batch roots, circuit hash enforcement, artifact gating, and an on-chain Groth16 verifier. That combination makes settlement proofs reliable rather than aspirational.

9) Who is the team behind Reveal Market, and what in your background made you want to build this particular kind of market?

The repository does not list team members or backgrounds. Provide the approved team bios and I will expand this answer in a polished, public-facing format.

10) Resolution is where prediction markets live or die. How do you determine the outcome of a market, handle ambiguity, and protect against bad resolution incentives?

The system ingests resolution data from trusted sources (Gamma/Goldsky/ConditionalTokens snapshots) and persists it; on-chain settlement uses the resolved outcome and emits resolution metadata. Clear market rules are critical: they define what counts as a valid outcome and how ambiguous edge cases are handled. If you have a formal dispute or governance process, share it and I will integrate it into a stronger public answer.

11) What kinds of markets are you prioritizing first (crypto, macro, sports, governance, ecosystem-specific), and why those categories?

The repo aligns with Polymarket-style feeds and Horizen testnet defaults, which suggests a focus on crypto and event markets where those feeds exist and resolution data is reliable. If you want to prioritize sports, macro, governance, or ecosystem-specific categories first, confirm the lineup and I will tailor the narrative to those priorities.

12) Why build Reveal Market in the Horizen ecosystem and under Project funding what specifically does Horizen enable for you that other stacks don't?

The codebase is built with Horizen testnet defaults and tooling (RPC, chain id, explorer) baked in, so the platform is already aligned to that ecosystem. If you want a sharper and more exciting claim about what Horizen enables (privacy primitives, throughput, cost, validator structure, or ecosystem incentives), provide those details and I will finalize a precise, defensible answer.

13) If Reveal Market succeeds, what does the Horizen community get out of it new users, new liquidity, new primitives for builders, or a new "privacy standard" for onchain markets?

It brings new users and liquidity into the ecosystem, and it introduces a privacy-forward market primitive that other builders can reuse. Because Reveal Market ships the full stack (streaming, hedging, relayer, proofs), it is not just a dapp; it is infrastructure that expands what can be built on Horizen. The long-term upside is a new standard for on-chain markets where live privacy is the default, not the exception.
