import Link from "next/link";
import { docsMetadata } from "@/lib/seo";

export const metadata = docsMetadata("overview");

export default function DocsOverview() {
  return (
    <>
      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
        Reveal Market
      </p>
      <h1 className="text-3xl font-semibold text-white">
        Where conviction meets privacy.
      </h1>
      <p>
        Reveal Market is a zero-knowledge prediction ecosystem built for
        institutions, liquidity partners, and power users who demand privately
        expressed conviction with publicly verifiable settlement. Every section
        of this briefing is designed to help investors, exchanges, and strategic
        operators understand the opportunity.
      </p>
      <div className="mt-8 grid gap-6 md:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <h2 className="text-xl font-semibold text-white">At a glance</h2>
          <ul className="mt-3 space-y-2 text-slate-200">
            <li>• zk-powered commit/reveal markets with instant finality</li>
            <li>• Institutional dashboards, API, and compliance tooling</li>
            <li>• Token utility tying fees, governance, and liquidity mining</li>
            <li>• Marketplace rails for branded partners</li>
          </ul>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <h2 className="text-xl font-semibold text-white">Read next</h2>
          <ul className="mt-3 space-y-2">
            <li>
              <Link href="/docs/manifesto" className="text-brand-300">
                Manifesto – why privacy-first alpha wins.
              </Link>
            </li>
            <li>
              <Link href="/docs/the-story" className="text-brand-300">
                The Story – traction, milestones, and roadmap.
              </Link>
            </li>
            <li>
              <Link href="/docs/tokenomics" className="text-brand-300">
                Tokenomics – incentive design & value capture.
              </Link>
            </li>
          </ul>
        </div>
      </div>
      <p className="mt-6 text-sm text-slate-400">
        Daily updates drop on{" "}
        <a
          href="https://x.com/RevealMarket"
          className="text-brand-300 underline"
          target="_blank"
          rel="noreferrer"
        >
          @RevealMarket
        </a>
        . Reach out via{" "}
        <a
          href="mailto:hello@revealmarket.xyz"
          className="text-brand-300 underline"
        >
          hello@revealmarket.xyz
        </a>{" "}
        for partner access.
      </p>
    </>
  );
}
