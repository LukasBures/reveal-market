export const metadata = {
  title: "Marketplace - Reveal Market Docs",
};

export default function MarketplacePage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">Sage Marketplace</h1>
      <p>
        Reveal Market aspires to host a decentralized marketplace for markets and
        liquidity providers. Operators can deploy factories with curated lists of
        markets, while third-party UIs surface them to end users.
      </p>
      <ul className="list-disc space-y-3 pl-6">
        <li>
          <strong>Market discovery</strong> – `/markets` endpoint powers listing
          UIs, filtering by category/oracle/status.
        </li>
        <li>
          <strong>Liquidity partners</strong> – Treasury addresses and rake
          managers can be configured per deployment to support different fee
          structures.
        </li>
        <li>
          <strong>Analytics</strong> – Stats endpoint summarises open vs. settled
          markets, rake distribution, and liquidity.
        </li>
      </ul>
      <p>
        Marketplace tooling (curated lists, watchlists, permissioned factories) is
        on the roadmap. Today, use the API + contracts to build your own explorer.
      </p>
    </>
  );
}
