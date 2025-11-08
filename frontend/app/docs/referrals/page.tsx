import { docsMetadata } from "@/lib/seo";

export const metadata = docsMetadata("referrals");

export default function ReferralsPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">Referrals</h1>
      <p>
        Growth is partner-led. Our referral framework rewards those who bring
        serious capital, media distribution, or deal flow into Reveal.
      </p>
      <p>
        Think of it as aligned economics rather than vanity codes: referral
        partners earn performance-based allocations in $REVEAL, fee rebates, or
        direct rev share depending on the users or liquidity introduced. The
        program is live for vetted institutions—contact us to learn more.
      </p>
    </>
  );
}
