export const metadata = {
  title: "Core Infrastructure - Reveal Market Docs",
};

export default function CoreInfrastructurePage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">Core Infrastructure</h1>
      <p>
        Reveal Market is composed of three pillars: the FastAPI service, the
        ingest worker, and the Foundry contracts. Each is containerised via
        Docker and orchestrated through Compose.
      </p>
      <ul className="list-disc space-y-3 pl-6">
        <li>
          <strong>FastAPI API</strong> – Serves REST endpoints, handles cache
          tags, exposes metrics, and runs Alembic migrations during startup.
        </li>
        <li>
          <strong>Worker daemon</strong> – Polls Polymarket feeds, persists
          markets/resolutions, triggers on-chain creations, and writes Redis
          heartbeats.
        </li>
        <li>
          <strong>Smart contracts</strong> – MarketFactory deploys clones of
          RevealMarket; RakeManager withdraws protocol rake; Verifier is the zk
          stub awaiting replacement.
        </li>
      </ul>
      <p>
        Compose services include Postgres, Redis, API, worker, and frontend.
        Health checks ensure containers are ready before they receive traffic.
      </p>
    </>
  );
}
