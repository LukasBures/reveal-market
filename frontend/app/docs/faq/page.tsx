export const metadata = {
  title: "FAQ - Reveal Market Docs",
};

export default function FAQPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">FAQ</h1>
      <dl className="space-y-6">
        <div>
          <dt className="font-semibold text-white">When does $REVEAL launch?</dt>
          <dd className="text-slate-300">
            Token generation is slated for H2 2025, with strategic partners and
            liquidity providers receiving priority allocations before the public
            phase.
          </dd>
        </div>
        <div>
          <dt className="font-semibold text-white">
            What is the investment thesis?
          </dt>
          <dd className="text-slate-300">
            Reveal captures protocol fees from a privacy-first derivatives market
            and shares them with token holders while expanding into branded
            marketplaces. Think of it as owning the “CME of zk prediction.”
          </dd>
        </div>
        <div>
          <dt className="font-semibold text-white">
            How can I participate?
          </dt>
          <dd className="text-slate-300">
            Become a liquidity partner, launch a marketplace, or invest directly
            via our allocations program. Email{" "}
            <a
              href="mailto:hello@revealmarket.xyz"
              className="text-brand-300 underline"
            >
              hello@revealmarket.xyz
            </a>{" "}
            to begin diligence.
          </dd>
        </div>
      </dl>
    </>
  );
}
