export const metadata = {
  title: "The Story So Far - Reveal Market Docs",
};

export default function StoryPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">The Story So Far</h1>
      <p>
        Reveal Market started as an experiment in pairing zk-proofs with
        prediction markets. Over time, the project grew into a full stack:
        Foundry contracts, FastAPI backend, ingest worker, and a React-based
        front-end.
      </p>
      <ul className="list-disc space-y-3 pl-6">
        <li>2023 Q3 – First RevealMarket.sol prototype deployed on testnet.</li>
        <li>
          2024 Q1 – FastAPI backend + worker added to keep off-chain and on-chain
          states in sync.
        </li>
        <li>
          2024 Q4 – Docs & marketing site launched to onboard partners and early
          traders.
        </li>
      </ul>
      <p>
        The immediate roadmap focuses on audited prover circuits, Horizen
        deployment, and wallet-native flows. Follow{" "}
        <a
          href="https://github.com/RevealMarket"
          className="text-brand-300 underline"
        >
          GitHub
        </a>{" "}
        for releases.
      </p>
    </>
  );
}
