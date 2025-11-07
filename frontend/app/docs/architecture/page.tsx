import { Code } from "@/components/docs/primitives";

export default function ArchitecturePage() {
  return (
    <>
      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
        Docs · Architecture
      </p>
      <h1 className="text-3xl font-semibold text-white">System design</h1>
      <p>
        Reveal Market is split across three domains: FastAPI backend (read/write
        API), async worker (Polymarket + on-chain ingestion), and the Foundry
        contracts (MarketFactory + RevealMarket). Redis caches query responses
        and heartbeats, while Postgres stores canonical markets.
      </p>
      <h2 className="text-2xl font-semibold text-white">Environment vars</h2>
      <Code>
        {`RM_DATABASE_URL=postgresql+psycopg2://market_admin:<REDACTED>@postgres:5432/reveal_market
RM_REDIS_URL=redis://redis:6379/0
NEXT_PUBLIC_API_BASE_URL=https://api.revealmarket.xyz
RM_API_BASE_URL=http://api:8000`}
      </Code>
      <h2 className="text-2xl font-semibold text-white">Data flow</h2>
      <ol className="list-decimal space-y-3 pl-6">
        <li>Worker polls upstream feeds + Conditional Tokens events.</li>
        <li>Worker upserts markets/resolutions via shared repository layer.</li>
        <li>API exposes filtered markets with Redis request caching.</li>
        <li>Frontend fetches via server components + React Query hydration.</li>
        <li>Users settle/claim via Wagmi + RevealMarket contracts.</li>
      </ol>
      <p>
        For further details inspect{" "}
        <Code inline>backend/README.md</Code> and{" "}
        <Code inline>contracts/README.md</Code>.
      </p>
    </>
  );
}
