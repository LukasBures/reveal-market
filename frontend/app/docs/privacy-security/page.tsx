export const metadata = {
  title: "Privacy & Security - Reveal Market Docs",
};

export default function PrivacySecurityPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">Privacy & Security</h1>
      <p>
        Commit-and-reveal flows provide privacy for market entrants; zero-knowledge
        proofs confirm settlement without revealing underlying commitments. Even so,
        operators must harden the stack:
      </p>
      <ul className="list-disc space-y-3 pl-6">
        <li>Use HTTPS + Cloudflare to terminate TLS before hitting the VPS.</li>
        <li>Store private keys in a secure vault (KMS, HashiCorp) rather than environment files.</li>
        <li>Separate RPC credentials per environment; never embed secrets in Docker images.</li>
        <li>Rotate Polymarket API keys, DB credentials, and wallet secrets regularly.</li>
      </ul>
      <p>
        Contract-level security audits and prover circuit reviews remain on the roadmap.
        Until then, treat the platform as experimental and limit mainnet exposure.
      </p>
    </>
  );
}
