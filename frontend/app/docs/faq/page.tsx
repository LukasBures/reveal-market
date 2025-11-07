export const metadata = {
  title: "FAQ - Reveal Market Docs",
};

export default function FAQPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">FAQ</h1>
      <dl className="space-y-6">
        <div>
          <dt className="font-semibold text-white">Is there a token?</dt>
          <dd className="text-slate-300">
            Not yet. Tokenomics are under review; no tokens have been issued.
          </dd>
        </div>
        <div>
          <dt className="font-semibold text-white">
            When will the zk verifier ship?
          </dt>
          <dd className="text-slate-300">
            Integrating a audited Groth16 verifier is a top priority before mainnet.
          </dd>
        </div>
        <div>
          <dt className="font-semibold text-white">
            Where can I follow development?
          </dt>
          <dd className="text-slate-300">
            GitHub (RevealMarket org) and future blog posts shared on the docs site.
          </dd>
        </div>
      </dl>
    </>
  );
}
