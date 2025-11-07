export const metadata = {
  title: "Manifesto - Reveal Market Docs",
};

export default function ManifestoPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">The Reveal Manifesto</h1>
      <p>
        Reveal Market is built around a few simple beliefs: private conviction
        should be rewarded, zero-knowledge systems should be accessible, and
        transparency should never come at the cost of user safety. Our manifesto
        explains the principles guiding the protocol.
      </p>
      <ol className="list-decimal space-y-4 pl-6">
        <li>
          <strong>Privacy-respecting liquidity.</strong> Commit-reveal
          interactions allow traders to contribute liquidity without exposing
          positions until settlement.
        </li>
        <li>
          <strong>Verifiable fairness.</strong> Every settlement emits
          verifiable proofs and on-chain events so outcomes remain auditable.
        </li>
        <li>
          <strong>Composable rails.</strong> APIs, worker daemons, and smart
          contracts remain modular so builders can integrate parts or the whole
          stack.
        </li>
      </ol>
      <p>
        Whether you are an operator, trader, or auditor, these values shape how
        Reveal Market will evolve.
      </p>
    </>
  );
}
