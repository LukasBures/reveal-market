export const metadata = {
  title: "Integrations - Reveal Market Docs",
};

export default function IntegrationsPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">Integrations</h1>
      <p>
        Developers can integrate with Reveal Market via REST endpoints, on-chain
        events, or the ingest worker hooks. Common integration paths:
      </p>
      <ul className="list-disc space-y-3 pl-6">
        <li>
          <strong>REST API</strong> –{" "}
          <code className="rounded bg-black/40 px-2 py-1">/markets</code>,{" "}
          <code className="rounded bg-black/40 px-2 py-1">
            /markets/
            {"{event_id}"}
          </code>
          ,{" "}
          <code className="rounded bg-black/40 px-2 py-1">
            /resolution/
            {"{condition}"}
          </code>
          . Supports filters, search, and stats.
        </li>
        <li>
          <strong>On-chain events</strong> – Listen for `MarketCreated`,
          `MarketResolved` (coming soon), and `GuardianUpdated` from the
          factory/market contracts.
        </li>
        <li>
          <strong>Worker hooks</strong> – Extend the ingest loop to publish to
          Kafka, WebSocket streams, or your own cache layer after each sync.
        </li>
      </ul>
      <p>
        For custom partnerships, contact{" "}
        <a
          href="mailto:hello@revealmarket.xyz"
          className="text-brand-300 underline"
        >
          hello@revealmarket.xyz
        </a>
        .
      </p>
    </>
  );
}
