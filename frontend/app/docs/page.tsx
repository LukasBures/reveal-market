import Link from "next/link";

export default function DocsOverview() {
  return (
    <>
      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
        Docs
      </p>
      <h1 className="text-3xl font-semibold text-white">Overview</h1>
      <p>
        Welcome to the Reveal Market documentation hub. Here you will find
        architectural deep dives, API references, and step-by-step guides for
        deploying markets and integrating wallets.
      </p>
      <ul className="list-disc space-y-2 pl-6">
        <li>
          <Link href="/docs/getting-started" className="text-brand-300">
            Getting started
          </Link>{" "}
          explains how to run backend, contracts, and frontend locally.
        </li>
        <li>
          <Link href="/docs/architecture" className="text-brand-300">
            Architecture
          </Link>{" "}
          covers the API, worker, and zk pipelines.
        </li>
        <li>
          <Link href="/docs/api" className="text-brand-300">
            API reference
          </Link>{" "}
          details REST endpoints exposed by the FastAPI service.
        </li>
      </ul>
      <p className="text-sm text-slate-400">
        News and release notes land on{" "}
        <a
          href="https://x.com/RevealMarket"
          className="text-brand-300 underline"
          target="_blank"
          rel="noreferrer"
        >
          @RevealMarket
        </a>{" "}
        as well.
      </p>
    </>
  );
}
