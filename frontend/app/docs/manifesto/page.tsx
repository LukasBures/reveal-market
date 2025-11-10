import type { Metadata } from "next";
import { docsMetadata } from "@/lib/seo";

export const metadata: Metadata = docsMetadata("manifesto");

export default function ManifestoPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">Manifesto</h1>
      <p>
        We believe alpha deserves protection, settlement must be instant, and
        liquidity should be rewarded without sacrificing privacy. Reveal Market
        exists to make those principles investable.
      </p>
      <ol className="list-decimal space-y-4 pl-6">
        <li>
          <strong>Trustless privacy.</strong> Traders express conviction
          privately via commit/reveal while zero-knowledge proofs audit every
          outcome. This unlocks institutional flows that will never leak their
          edge.
        </li>
        <li>
          <strong>Institution-ready rails.</strong> Compliance dashboards,
          audited smart contracts, and an API-first approach let exchanges and
          OTC desks plug in without rearchitecting their stack.
        </li>
        <li>
          <strong>Aligned incentives.</strong> Liquidity providers, guardians,
          and token holders capture value through fee reductions, governance, and
          deal flow. Nobody contributes for free.
        </li>
      </ol>
      <p>
        The opportunity is simple: capture the fastest-growing segment of
        on-chain prediction volume by offering a product the market actually
        trusts. Partners that join now shape the governance, product roadmap, and
        future economics.
      </p>
    </>
  );
}
