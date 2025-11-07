export const metadata = {
  title: "Tokenomics - Reveal Market Docs",
};

export default function TokenomicsPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">$REVEAL Tokenomics</h1>
      <p>
        Token design is still under review. The current thinking mirrors
        standard marketplaces:
      </p>
      <ul className="list-disc space-y-3 pl-6">
        <li>
          <strong>Utility</strong> – reduced protocol rake, governance over
          guardian policies, staking for dispute resolution.
        </li>
        <li>
          <strong>Emission</strong> – linear release aligned with marketplace
          growth, with staking incentives for oracle operators.
        </li>
        <li>
          <strong>Distribution</strong> – split between community, core team,
          and strategic partners (exact percentages TBD).
        </li>
      </ul>
      <p>
        Final token mechanics will be published before mainnet launch. Until
        then, no tokens have been issued—beware of scams.
      </p>
    </>
  );
}
