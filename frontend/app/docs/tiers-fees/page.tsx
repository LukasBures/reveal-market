export const metadata = {
  title: "Tiers & Fees - Reveal Market Docs",
};

export default function TiersFeesPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">Tiers & Fees</h1>
      <p>
        Rake is configurable per deployment via `RakeManager`. Default cap is 2%
        (200 bps). Future releases may add tiered fees:
      </p>
      <ul className="list-disc space-y-3 pl-6">
        <li>
          <strong>Community</strong> – 1% rake, basic analytics, standard SLAs.
        </li>
        <li>
          <strong>Pro</strong> – 0.5% rake, priority ingest, custom alerting.
        </li>
        <li>
          <strong>Enterprise</strong> – bespoke rake, dedicated guardian,
          private RPC endpoints.
        </li>
      </ul>
      <p>
        Today, adjust rake via `setRakeBps` or a per-market override when calling
        `createMarket`. Front-end surfaces should display the applied rake (see
        `RevealMarket.appliedRakeBps()`).
      </p>
    </>
  );
}
