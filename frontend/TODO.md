# Frontend Investor Roadmap

The web experience is our public pitch deck. Every sprint should reinforce why Reveal Market is a differentiated investment opportunity and make it effortless for partners to engage.

## Immediate Polish Gaps (Q1 2025)

- **Replace placeholder price chart** – `MarketDetailChart` still renders a mocked area graph. Swap it for real historical liquidity/probability pulled from the backend (or worker summaries) so detail pages show living data instead of a static image.
- **Global search UX** – Current search only filters the featured grid. Add a `/markets/search` view (with keyboard hints + slugged URLs) that paginates true API results, surfaces category pills, and mirrors the crypto-native instant feedback users expect.
- **Docs layout on small screens** – The new lazy docs nav is desktop-perfect but still sticky on phones. Introduce a sheet/drawer interaction so the nav collapses behind a “Docs menu” button on screens `<1024px`.
- **Proof filters & exports** – `/proofs` now streams via infinite scroll but lacks filters (status, verifier, market) and CSV export. Add a filter bar plus a `Download receipts` button that grabs the currently loaded window for diligence teams.
- **Partner trust banners** – Homepage still needs investor/partner badges, earned media quotes, and integrations grid to meet the “ultra-polished crypto venue” bar mentioned in AGENTS.md.
- **A11y sweep** – Add focus outlines for glassmorphism buttons, ensure WCAG contrast for brand gradients, and audit ARIA labels on nav/search so institutional visitors with assistive tech have zero friction.

## Phase 1 – Trust & Narrative Foundation

- **Hero storytelling refresh**
  Craft above-the-fold copy that articulates the value proposition (regulated-grade prediction markets, Horizen moat, zk-enabled settlement). Pair with live traction stats and a persistent CTA toward partnership outreach.

- **Homepage segmentation**
  Serve differentiated hero copy and callouts for builders vs. investors vs. liquidity partners (even simple query-param toggles). Today every visitor sees the same narrative; personalization shows we understand their goals.

- **Investor proof points section**
  Showcase treasury growth, market throughput, and rake distribution in a simple KPI grid. Cite verifiable sources (health endpoints, on-chain stats) to underscore transparency.

- **Social credibility**
  Surface the [@RevealMarket](https://x.com/RevealMarket) feed, earned media quotes, and investor testimonials to signal momentum. Include compliance-friendly disclosure text below each card.

- **Docs navigation overhaul**
  Reorganize `/docs` into investor-relevant narratives: Vision, Roadmap, Tokenomics, Infrastructure, Legal. Ensure each page funnels users toward “Connect With The Team”.

## Phase 2 – Data Transparency & Conversion

- **Interactive metrics hub**
  Build a dashboard that consumes `/markets/stats` plus curated worker metrics to visualize liquidity depth, settlement speed, and fee capture. Allow CSV/PDF export so funds can drop data into diligence memos.

- **Deal-flow CTAs**
  Add modular lead forms (Strategic Investment, Liquidity Partnership, Exchange Integration) with CRM hooks. Highlight expected response times and confidentiality statements.

- **Case studies carousel**
  Present 2–3 anonymized partner stories showing how Reveal Market improved spreads or unlocked new revenue. Include KPIs (e.g., 30% faster resolution, X bps rake share) and link to deeper dives in docs.

- **Localized credibility**
  Introduce geo-targeted badges (e.g., “Optimized for EU-compliant venues”) driven by feature flags so regulated partners immediately see relevance.

## Phase 3 – Partnership Workflows

- **Due-diligence vault**
  Create a gated download center for audited smart-contract reports, SOC readiness notes, and technical one-pagers. Gate access via email verification to capture serious leads.

- **Live ops status**
  Integrate status badges for API/worker/contract uptime with direct links to the health endpoints. Investors should see operational excellence at a glance.

- **Event & roadmap calendar**
  Embed timelines for upcoming launches (Groth16 verifier, Horizen ZEN testnet rollout, token events). Allow users to subscribe via iCal or add to Google Calendar.

- **Performance & accessibility hardening**
  Hit sub-1s Largest Contentful Paint on global CDNs, ship full accessibility audits, and maintain Lighthouse 90+ so enterprise visitors experience no friction.

## Cross-Cutting Initiatives

- **Design system**
  Maintain a polished, investor-ready component library with consistent typography, gradients, and iconography that echo the financial-services aesthetic.

- **Narrative governance**
  Keep messaging synchronized with backend/contract milestones so every doc page, footer blurb, and CTA reflects the latest roadmap realities.

- **Experimentation loop**
  Instrument pages with privacy-conscious analytics to test CTA placement, social proof ordering, and copy variants aimed at institutional visitors.

## Near-Term Engineering Enhancements

- **Real market telemetry**
  Replace the synthetic `MarketDetailChart` with live price/liquidity history pulled from the API or a lightweight worker summary so market pages demonstrate actual performance.

- **Dynamic imports for heavy modules**
  Load secondary surfaces (proof receipts, docs navigation, metadata panels) via `next/dynamic` to trim the initial JS chunk served to homepage visitors.

- **Proof receipts pagination**
  Convert `/proofs` into a streaming view with server actions or infinite scroll. Right now the page renders the entire dataset, which won’t scale as receipts grow.

- **Structured logging hooks**
  Surface client-side logger events (e.g., failed fetches, slow renders) to an observability endpoint so ops can correlate frontend issues with backend health in Docker logs.

- **Accessibility sweep**
  Add keyboard focus outlines, ARIA labels for every CTA, and verify color contrast for the glassmorphism palette. Document the guidelines in the design system.

- **Cache-aware fetch helpers**
  Introduce stale-while-revalidate hooks for `fetchFeaturedMarkets` so category pages stay snappy while new data streams in. Document the caching strategy in the README.

The frontend is the loudspeaker for fundraising, partnerships, and liquidity programs—build it with the same rigor as the core protocol so every visit nudges stakeholders closer to engagement.
