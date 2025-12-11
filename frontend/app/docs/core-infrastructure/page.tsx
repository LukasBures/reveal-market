import type { Metadata } from "next";
import { DocsStructuredData } from "@/components/docs/DocsStructuredData";
import { docsMetadata } from "@/lib/seo";

export const metadata: Metadata = docsMetadata("core-infrastructure");

export default function CoreInfrastructurePage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">Core Infrastructure</h1>
      <p>
        Under the hood, Reveal Market is built like a bank-grade trading system
        with the agility of a DeFi protocol. Investors care because this
        translates to uptime, compliance, and ability to scale beyond hobbyist
        venues.
      </p>
      <ul className="list-disc space-y-3 pl-6">
        <li>
          <strong>Always-on orchestration.</strong> Redundant services, health
          probes, and automated rollouts keep throughput high even during market
          spikes.
        </li>
        <li>
          <strong>Data fidelity.</strong> High-frequency ingestion pipelines and
          integrity proofs ensure settlement data is tamper evident.
        </li>
        <li>
          <strong>Security stack.</strong> Segregated secrets, guardian
          controls, and optional KYC/AML hooks satisfy institutional mandates.
        </li>
      </ul>
      <p>
        This is the infrastructure moat: Reveal blends the rigor institutions
        expect with the growth curves only crypto can deliver.
      </p>
      <DocsStructuredData slug="core-infrastructure" />
    </>
  );
}
