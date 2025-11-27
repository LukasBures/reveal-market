import Link from "next/link";
import type { Metadata } from "next";
import { docsMetadata } from "@/lib/seo";

export const metadata: Metadata = docsMetadata("overview");

export default function DocsOverview() {
  return (
    <>
      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Investor briefing</p>
      <h1 className="text-3xl font-semibold text-white">
        The diligence companion for Reveal Market.
      </h1>
      <p>
        This portal reframes the entire stack around the questions LPs, exchanges, and strategic investors ask in data
        rooms: why privacy matters, how fees accrue, what the roadmap looks like, and which controls keep regulators
        comfortable. Each section links directly to the underlying systems so your team can verify claims in minutes.
      </p>
      <div className="mt-8 grid gap-6 md:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <h2 className="text-xl font-semibold text-white">At a glance</h2>
          <ul className="mt-3 space-y-2 text-slate-200">
            <li>• ZK commit/reveal + on-chain attestations for every settlement</li>
            <li>• Schema-tagged caches & KPIs surfaced via the public API</li>
            <li>• Tokenomics that tie rake capture, governance, and liquidity rewards</li>
            <li>• Legal + ops playbooks aligned to institutional diligence</li>
          </ul>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <h2 className="text-xl font-semibold text-white">Read next</h2>
          <ul className="mt-3 space-y-2">
            <li>
              <Link href="/docs/roadmap" className="text-brand-300">
                Execution Roadmap – milestones investors are tracking.
              </Link>
            </li>
            <li>
              <Link href="/docs/tokenomics" className="text-brand-300">
                Tokenomics – where value accrues across fees & governance.
              </Link>
            </li>
            <li>
              <Link href="/docs/privacy-security" className="text-brand-300">
                Privacy & Security – controls that keep alpha protected.
              </Link>
            </li>
          </ul>
        </div>
      </div>
      <div className="mt-6 rounded-2xl border border-white/10 bg-white/5 p-5">
        <p className="text-sm text-slate-300">
          Need direct access to the data room, KPI exports, or the founding team? Use the{" "}
          <Link href="/contact" className="text-brand-300 underline">
            contact form
          </Link>{" "}
          and we will schedule a diligence walkthrough.
        </p>
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
        . Partner access requests can be shared through the{" "}
        <Link href="/contact" className="text-brand-300 underline">
          contact form
        </Link>
        .
      </p>
    </>
  );
}
