import Link from "next/link";
import { buildMetadata } from "@/lib/seo";

export const metadata = buildMetadata({
  title: "About Reveal Market",
  description:
    "Reveal Market pairs zero-knowledge prediction rails with institution-ready infrastructure and a clear roadmap.",
  path: "/about",
  keywords: [
    "about reveal market",
    "prediction market team",
    "institutional infrastructure",
  ],
});

export default function AboutPage() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-16">
      <p className="text-xs uppercase tracking-[0.3em] text-slate-400">
        About
      </p>
      <h1 className="mt-4 text-4xl font-semibold text-white">
        Built for high-signal traders & builders.
      </h1>
      <p className="mt-6 text-lg text-slate-300">
        Reveal Market couples a hardened FastAPI backend, async ingestion
        worker, Redis edge caching, and Foundry-based smart contracts. Our
        commit-and-reveal design keeps alpha private until settlement, while
        zk-proof verification ensures payouts remain trustless.
      </p>
      <div className="mt-10 grid gap-6 md:grid-cols-2">
        <div className="rounded-2xl border border-white/10 p-5">
          <h3 className="text-xl font-semibold text-white">What’s live</h3>
          <ul className="mt-4 list-disc space-y-2 pl-5 text-slate-300">
            <li>FastAPI read/write surface with Redis-backed caching.</li>
            <li>Worker daemon syncing Polymarket + on-chain deployments.</li>
            <li>zk-powered RevealMarket + MarketFactory contracts.</li>
          </ul>
        </div>
        <div className="rounded-2xl border border-white/10 p-5">
          <h3 className="text-xl font-semibold text-white">What’s next</h3>
          <ul className="mt-4 list-disc space-y-2 pl-5 text-slate-300">
            <li>Wallet-native onboarding with Wagmi + RainbowKit.</li>
            <li>Horizen and Polygon deployment presets.</li>
            <li>Full docs site at docs.revealmarket.xyz.</li>
          </ul>
        </div>
      </div>
      <div className="mt-10 rounded-2xl border border-white/10 bg-white/5 p-6">
        <h2 className="text-2xl font-semibold text-white">Questions?</h2>
        <p className="mt-3 text-slate-300">
          Read the{" "}
          <Link
            href="/docs"
            className="text-brand-300 underline decoration-brand-400"
          >
            docs
          </Link>{" "}
          or email{" "}
          <a
            href="mailto:hello@revealmarket.xyz"
            className="text-brand-300 underline decoration-brand-400"
          >
            hello@revealmarket.xyz
          </a>
          .
        </p>
      </div>
    </div>
  );
}
