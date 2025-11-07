export const metadata = {
  title: "Marketplace - Reveal Market Docs",
};

export default function MarketplacePage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">Marketplace Flywheel</h1>
      <p>
        Reveal Market is building the infrastructure for premium prediction
        venues. Think of it as a white-label L1 for conviction: partners launch
        their own experiences while sharing liquidity and trust.
      </p>
      <ul className="list-disc space-y-3 pl-6">
        <li>
          <strong>Market discovery.</strong> Curated front-ends, embeddable
          widgets, and programmatic feeds ensure audiences can tap into the most
          active markets instantly.
        </li>
        <li>
          <strong>Liquidity partners.</strong> Treasury addresses and rake
          managers can be configured per deployment, allowing bespoke fee
          structures and private liquidity pools.
        </li>
        <li>
          <strong>Analytics.</strong> Real-time stats on open vs. settled
          markets, fee flows, and user cohorts inform product and investment
          decisions.
        </li>
      </ul>
      <p>
        This marketplace layer is the moat: once liquidity and data live atop
        Reveal, every partner benefits from network effects.
      </p>
    </>
  );
}
