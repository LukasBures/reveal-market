import { docsMetadata } from "@/lib/seo";

export const metadata = docsMetadata("tokenomics");

export default function TokenomicsPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">$REVEAL Economics</h1>
      <p>
        The $REVEAL token underpins the marketplace. Its design aligns liquidity
        providers, governance, and long-term value accrual.
      </p>
      <ul className="list-disc space-y-3 pl-6">
        <li>
          <strong>Utility.</strong> Fee discounts, boosted liquidity rewards,
          governance rights, and access to premium market creation tools.
        </li>
        <li>
          <strong>Emission.</strong> Targeted to liquidity growth; a portion is
          reserved for strategic partners and ecosystem funds, vesting alongside
          traction milestones.
        </li>
        <li>
          <strong>Value capture.</strong> Protocol rake is split between
          treasury, buy-backs, and partner incentives, ensuring token demand
          tracks platform usage.
        </li>
      </ul>
      <p className="mt-4 text-sm text-slate-400">
        Token launch timeline and exact allocations will be disclosed to
        investors under NDA prior to public release. Beware of impostor tokens—
        no public sale is live at this time.
      </p>
    </>
  );
}
