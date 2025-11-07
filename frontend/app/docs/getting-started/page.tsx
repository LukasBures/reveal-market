import Link from "next/link";

export default function GettingStartedPage() {
  return (
    <>
      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
        Docs · Guide
      </p>
      <h1 className="text-3xl font-semibold text-white">Getting started</h1>
      <ol className="list-decimal space-y-4 pl-6">
        <li>
          <strong>Clone the repo</strong> and install dependencies for each
          surface:
          <pre className="mt-2 rounded-xl bg-black/40 p-3 text-xs text-white">
            git clone git@github.com:RevealMarket/reveal-market.git
            {"\n"}cd reveal-market {"\n"}poetry install --directory backend/api{" "}
            {"\n"}poetry install --directory backend/worker {"\n"}npm install
            --prefix frontend
          </pre>
        </li>
        <li>
          <strong>Launch Docker stack</strong> (Postgres, Redis, API, worker,
          frontend):
          <pre className="mt-2 rounded-xl bg-black/40 p-3 text-xs text-white">
            backend/run_local.sh
          </pre>
        </li>
        <li>
          <strong>Deploy contracts</strong> with Foundry:
          <pre className="mt-2 rounded-xl bg-black/40 p-3 text-xs text-white">
            cd contracts {"\n"}forge build && forge script script/Deploy.s.sol
          </pre>
        </li>
        <li>
          <strong>Connect wallets</strong> (coming soon). We bootstrap Wagmi +
          viem via{" "}
          <code className="rounded bg-black/40 px-2 py-1">
            lib/wagmi.ts
          </code>{" "}
          so adding RainbowKit or custom connectors is straightforward.
        </li>
      </ol>
      <p>
        Need help? Open an issue or email{" "}
        <a
          href="mailto:hello@revealmarket.xyz"
          className="text-brand-300 underline"
        >
          hello@revealmarket.xyz
        </a>
        .
      </p>
      <p>
        Next:{" "}
        <Link href="/docs/architecture" className="text-brand-300">
          architecture deep dive
        </Link>
        .
      </p>
    </>
  );
}
