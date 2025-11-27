import type { Metadata } from "next";
import Link from "next/link";
import { docsMetadata } from "@/lib/seo";

export const metadata: Metadata = docsMetadata("getting-started");

export default function GettingStartedPage() {
  return (
    <>
      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
        Partner Playbook
      </p>
      <h1 className="text-3xl font-semibold text-white">
        How to engage with Reveal Market
      </h1>
      <ol className="list-decimal space-y-6 pl-6">
        <li>
          <h3 className="font-semibold text-white">Request partner access</h3>
          <p className="text-slate-300">
            Use the{" "}
            <Link href="/contact" className="text-brand-300 underline">
              contact form
            </Link>{" "}
            to request the investor deck, compliance packet, and marketplace sandbox credentials.
          </p>
        </li>
        <li>
          <h3 className="font-semibold text-white">Choose your role</h3>
          <p className="text-slate-300">
            Become a liquidity partner (earn rake share), a branded marketplace
            operator (white-label UI), or a data/API consumer (embed markets into
            your app). Each tier carries specific benefits and allocations.
          </p>
        </li>
        <li>
          <h3 className="font-semibold text-white">Integrate & launch</h3>
          <p className="text-slate-300">
            Our team co-pilots technical integration, provides marketing assets,
            and lines up press/launch support. Governance and token details will
            be shared directly during diligence.
          </p>
        </li>
      </ol>
      <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-slate-200">
        Fast-track slots are limited each quarter. Reach out early to secure a
        preferred role in the ecosystem.
      </div>
    </>
  );
}
