import { docsMetadata } from "@/lib/seo";

export const metadata = docsMetadata("roadmap");

export default function RoadmapPage() {
  return (
    <>
      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Execution</p>
      <h1 className="text-3xl font-semibold text-white">Roadmap & Diligence Milestones</h1>
      <p>
        The Reveal Market roadmap is designed around the proof points that investment committees ask about most:
        verifiable data assurance, liquidity automation, and compliance readiness. Each pillar below has clear outcomes
        and supporting artifacts so partners can track progress in real time.
      </p>
      <section className="space-y-4">
        <div>
          <h2 className="text-2xl font-semibold text-white">Pillar 1 · Data Assurance</h2>
          <ul className="list-disc space-y-3 pl-6">
            <li>
              <strong>Worker-led schema enforcement.</strong> Alembic migrations and schema tags now run directly from
              the ingestion worker, preventing drift in single-service deployments.
            </li>
            <li>
              <strong>Resolution ledger.</strong> Continuous hydration of on-chain payouts (block + tx hash) into Postgres
              and Redis for immutable audit trails.
            </li>
            <li>
              <strong>Cache tagging by schema version.</strong> `/markets` payloads are tied to revision IDs so stale data
              is automatically flushed.
            </li>
          </ul>
        </div>
        <div>
          <h2 className="text-2xl font-semibold text-white">Pillar 2 · Liquidity Automation</h2>
          <ul className="list-disc space-y-3 pl-6">
            <li>
              <strong>Polymarket ingestion resilience.</strong> Shared retry + metrics stack with alerting on upstream
              error ratios.
            </li>
            <li>
              <strong>Resolution automation loop.</strong> Worker triggers settlement transactions and de-duplicates retries
              for lower operational burden.
            </li>
            <li>
              <strong>Environment-aware cache namespaces.</strong> Prevents staging/production cross-talk when partners run
              back-to-back demos.
            </li>
          </ul>
        </div>
        <div>
          <h2 className="text-2xl font-semibold text-white">Pillar 3 · Institutional Readiness</h2>
          <ul className="list-disc space-y-3 pl-6">
            <li>
              <strong>Docs & legal alignment.</strong> Investor narratives, legal center links, and CTA funnels that push
              prospects directly to the diligence inbox.
            </li>
            <li>
              <strong>Structured tracing.</strong> OpenTelemetry spans that connect API requests, Redis cache hits, and
              worker batches for external observability platforms.
            </li>
            <li>
              <strong>Horizen ZEN testnet support.</strong> Regulated partners can dress-rehearse deployments before
              moving capital.
            </li>
          </ul>
        </div>
      </section>
      <div className="mt-8 rounded-2xl border border-white/10 bg-white/5 p-5">
        <p className="text-sm text-slate-300">
          Need a milestone-by-milestone walkthrough or the latest KPI exports?{" "}
          <a
            href="mailto:hello@revealmarket.xyz?subject=Reveal%20Market%20Roadmap"
            className="text-brand-300 underline"
          >
            Connect with the team
          </a>{" "}
          for a tailored diligence session.
        </p>
      </div>
    </>
  );
}
