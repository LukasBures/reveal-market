import type { Metadata } from "next";
import { docsMetadata } from "@/lib/seo";

export const metadata: Metadata = docsMetadata("integrations");

export default function IntegrationsPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">Integrations</h1>
      <p>
        Reveal Market is open for business integrations across exchanges, media
        brands, structured product desks, and analytics providers. Plugging into
        the protocol exposes live market intelligence and turnkey monetisation.
      </p>
      <ul className="list-disc space-y-3 pl-6">
        <li>
          <strong>Data/API Access.</strong> Institutional endpoints provide
          filtered market feeds, liquidity stats, and settlement history for
          embedding inside trading tools or research portals.
        </li>
        <li>
          <strong>Marketplace SDK.</strong> Launch a branded prediction venue on
          top of Reveal’s contracts while keeping fee control, UX, and audience.
        </li>
        <li>
          <strong>Liquidity partner APIs.</strong> Programmatically seed or
          rebalance positions, receive rake-sharing, and access treasury
          analytics.
        </li>
      </ul>
      <p>
        The integration team handles technical scoping and prioritises
        partnerships that expand geographic reach or bring novel distribution.
        Begin the conversation at{" "}
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
