export const metadata = {
  title: "Disclaimer - Reveal Market",
};

export default function DisclaimerPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-16 text-slate-200">
      <h1 className="text-3xl font-semibold text-white">Disclaimer</h1>
      <p className="mt-4">
        Reveal Market is experimental software. Nothing on this site constitutes
        financial, legal, or investment advice.
      </p>
      <ul className="mt-8 space-y-4 list-disc pl-6">
        <li>
          Markets may be volatile, illiquid, or unavailable depending on
          jurisdiction.
        </li>
        <li>
          Smart contracts can contain bugs. Do your own research before using
          them.
        </li>
        <li>
          Reveal Market does not custody funds or guarantee payouts; users
          interact with contracts at their own risk.
        </li>
      </ul>
      <p className="mt-8 text-sm text-slate-400">
        Use the platform responsibly and consult professionals if you have legal
        or tax questions.
      </p>
    </div>
  );
}
