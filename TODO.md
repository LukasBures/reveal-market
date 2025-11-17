• Backend Gaps

  - Data-assurance features are still absent: there’s no AI summary ledger/provenance trail, no request-scoped latency logging, and no persistent resolution ledger, so /markets can’t yet prove narrative lineage, SLA adherence, or settlement metadata (backend/TODO.md:7, backend/TODO.md:10, backend/
    TODO.md:19).
  - Worker observability/resilience work remains: cache invalidation is still coarse, the large worker routines need decomposition, and service heartbeats aren’t exposed via a dashboard, leaving ops blind to drift (backend/TODO.md:16, backend/TODO.md:25, backend/TODO.md:37).
  - Liquidity automation gaps include missing Polymarket retries/backoff, unmanaged signer secrets, no config hot-reload, and no scalable AI summary sidecar, so ingestion and automation can’t meet enterprise reliability targets (backend/TODO.md:42, backend/TODO.md:45, backend/TODO.md:48, backend/TODO.md:54).
  - Institutional readiness items—integration-grade pytest-docker suites, OpenTelemetry tracing, autoscaling hooks, richer /markets payloads, and tamper-evident export tooling—are all still on paper, limiting investor diligence support (backend/TODO.md:71, backend/TODO.md:74, backend/TODO.md:81, backend/
    TODO.md:84, backend/TODO.md:86).

  Contracts Gaps

  - Groth16 verifier work isn’t complete: production keys, rotation tooling, and proof replay persistence remain missing, so zk settlement can’t yet be audited end-to-end (contracts/TODO.md:7, contracts/TODO.md:10).
  - Deployment/ops tooling such as consuming last-deployment.json, adding invariants/fuzz gates, and rehearsing ownership or guardian transfers is still outstanding, leaving governance brittle (contracts/TODO.md:16, contracts/TODO.md:19, contracts/TODO.md:22).
  - Treasury mechanics—validated rake overrides, flexible routing, metadata lifecycle definitions, and guardian operating models—are still unimplemented, so revenue reporting and compliance narratives can’t be backed by code/tests (contracts/TODO.md:27, contracts/TODO.md:30, contracts/TODO.md:33, contracts/
    TODO.md:36).
  - Expansion readiness like Horizen ZEN testnet tooling, upgradeable verifier registry, gas regression gates, cross-chain planning, and backend-aligned settlement helpers have yet to start, blocking multi-chain/institutional pilots (contracts/TODO.md:39, contracts/TODO.md:44, contracts/TODO.md:47,
    contracts/TODO.md:50, contracts/TODO.md:53).

  Frontend Gaps

  - Immediate polish work is undone: the market detail chart still shows mock data, global search lacks a dedicated view, docs nav isn’t mobile-friendly, proofs lack filters/exports, partner trust banners are missing, and an accessibility sweep hasn’t happened (frontend/TODO.md:7-12).
  - Narrative foundation items—hero copy refresh, segmented messaging, investor KPI proof points, social credibility, and reorganized docs—are still pending, so the site can’t yet address different stakeholder personas (frontend/TODO.md:16-29).
  - Transparency/conversion tooling like a metrics hub, tailored lead forms, case studies, and localized credibility badges haven’t shipped, limiting diligence funnels (frontend/TODO.md:33-43).
  - Partnership workflow support (due-diligence vault, live ops status, roadmap calendar, hardened performance/accessibility) remains unbuilt, so enterprise visitors can’t self-serve readiness signals (frontend/TODO.md:47-58).
  - Engineering enhancements—dynamic imports, scalable proof pagination, client-side structured logging, and cache-aware fetch helpers—are outstanding, so the app still ships heavier bundles and has limited observability/control over stale data (frontend/TODO.md:72-88).

  Proover Gaps

  - Performance profiling and possible rapidsnark pooling/daemonization haven’t been implemented, so prover latency bottlenecks are unknown (proover/TODO.md:5-7).
  - Observability lacks Prometheus exports and rolling latency/concurrency metrics, preventing production-grade monitoring (proover/TODO.md:9-11).
  - Artifact management helpers (pre-boot validation, packaged circuit assets) are missing, leaving operators to handle keys manually (proover/TODO.md:13-15).
  - Security/ergonomics work—dedicated linting in CI, non-root usage guidance, .env.proover samples, and env validation—is incomplete, so hardening and setup remain ad hoc (proover/TODO.md:17-23).
  - Longer-term roadmap items like cgo-based rapidsnark embedding and documented upgrade procedures are still open, so future-proofing the prover isn’t addressed (proover/TODO.md:25-27).
