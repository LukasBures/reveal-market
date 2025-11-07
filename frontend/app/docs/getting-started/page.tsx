import Link from "next/link";
import type { Route } from "next";

type Step = {
  title: string;
  description: string;
  code?: string;
};

const steps: Step[] = [
  {
    title: "Clone repositories & install deps",
    description:
      "Grab the repo, install Python + Node requirements, and provision Forge.",
    code: `git clone git@github.com:RevealMarket/reveal-market.git
cd reveal-market
poetry install --directory backend/api
poetry install --directory backend/worker
npm install --prefix frontend
forge install`,
  },
  {
    title: "Run services locally",
    description:
      "Compose spins up Postgres, Redis, API, worker, and frontend containers.",
    code: `./run_local.sh          # no-cache rebuild
# or
backend/run_local.sh      # reuses cached layers for backend iteration`,
  },
  {
    title: "Deploy contracts",
    description: "Use Foundry to deploy MarketFactory, RevealMarket, etc.",
    code: `cd contracts
forge build
forge script script/Deploy.s.sol --rpc-url <RPC> --private-key <KEY>`,
  },
  {
    title: "Configure env vars",
    description:
      "Copy `.env.example`, set RM_DATABASE_URL, RM_REDIS_URL, RPCs, wallet keys.",
    code: `cp .env.example .env
# edit .env to include RM_DATABASE_URL, RM_REDIS_URL, RM_RPC_URL, etc.`,
  },
];

type NextLink = {
  href: Route;
  label: string;
};

const nextLinks: NextLink[] = [
  { href: "/docs/architecture", label: "Architecture" },
  { href: "/docs/integrations", label: "Integrations" },
];

export default function GettingStartedPage() {
  return (
    <>
      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
        Docs · Guide
      </p>
      <h1 className="text-3xl font-semibold text-white">Getting started</h1>
      <ol className="list-decimal space-y-6 pl-6">
        {steps.map((step) => (
          <li key={step.title}>
            <h3 className="font-semibold text-white">{step.title}</h3>
            <p className="text-slate-300">{step.description}</p>
            {step.code && (
              <pre className="mt-2 rounded-xl bg-black/40 p-3 text-xs text-white whitespace-pre-wrap">
                {step.code}
              </pre>
            )}
          </li>
        ))}
      </ol>
      <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-slate-200">
        Need help? Email{" "}
        <a
          href="mailto:hello@revealmarket.xyz"
          className="text-brand-300 underline"
        >
          hello@revealmarket.xyz
        </a>{" "}
        or open an issue on GitHub.
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm text-slate-300">
        <span>Next:</span>
        {nextLinks.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className="rounded-full border border-white/20 px-3 py-1 text-white hover:bg-white/10"
          >
            {link.label}
          </Link>
        ))}
      </div>
    </>
  );
}
