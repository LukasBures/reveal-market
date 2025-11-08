import { docsMetadata } from "@/lib/seo";

export const metadata = docsMetadata("privacy-security");

export default function PrivacySecurityPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">Privacy & Security</h1>
      <p>
        Privacy is a competitive advantage and a regulatory requirement. Reveal
        combines zk proofs with institution-grade controls so compliance teams
        and traders both win.
      </p>
      <ul className="list-disc space-y-3 pl-6">
        <li>
          <strong>Zero-knowledge settlement.</strong> Claims are verified
          without revealing strategies; proofs are publicly auditable.
        </li>
        <li>
          <strong>Control planes.</strong> Guardians, pause switches, and
          alerting satisfy operational risk policies.
        </li>
        <li>
          <strong>Compliance-ready hooks.</strong> Optional KYB/KYC modules,
          sanction screening, and configurable geo-fencing.
        </li>
      </ul>
      <p>
        Security audits and formal verification are ongoing; investors receive
        full reports under NDA. The objective is simple: own the world’s most
        trusted privacy-preserving prediction rails.
      </p>
    </>
  );
}
