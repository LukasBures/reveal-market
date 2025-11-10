import type { Metadata } from "next";
import { docsMetadata } from "@/lib/seo";

export const metadata: Metadata = docsMetadata("tiers-fees");

export default function TiersFeesPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">Tiers & Fees</h1>
      <p>
        Reveal Market rewards early partners with preferential economics. Fee
        structures adapt to the role you play in the ecosystem.
      </p>
      <ul className="list-disc space-y-3 pl-6">
        <li>
          <strong>Launch Partners.</strong> Discounted rake, featured placement,
          co-marketing, and governance seats.
        </li>
        <li>
          <strong>Liquidity Syndicates.</strong> Revenue share from protocol
          fees plus custom dashboards and automated payouts.
        </li>
        <li>
          <strong>Enterprise.</strong> Bespoke pricing, dedicated guardian
          instances, and private routing of high-value flows.
        </li>
      </ul>
      <p>
        Pricing conversations happen with the founding team. Reach out to
        discuss volume commitments and we’ll tailor the tier to your business.
      </p>
    </>
  );
}
