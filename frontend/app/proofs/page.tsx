import type { Metadata } from "next";

import dynamic from "next/dynamic";
import { fetchProofReceipts } from "@/lib/api";
import { buildBreadcrumbJsonLd, buildMetadata } from "@/lib/seo";
import { JsonLd } from "@/components/seo/JsonLd";

const ProofsClient = dynamic(
  () => import("@/components/proofs/ProofsClient").then((mod) => ({ default: mod.ProofsClient })),
  {
    loading: () => (
      <div className="rounded-3xl border border-white/10 bg-slate-950/40 p-6 text-center text-slate-300">
        Loading proof receipts…
      </div>
    ),
  },
);

export const metadata: Metadata = buildMetadata({
  title: "Proof Receipts | Reveal Market",
  description:
    "Inspect Groth16 settlement proofs, replay-safe nonces, and zkVerify receipts emitted by the Reveal Market protocol.",
  path: "/proofs",
  keywords: ["reveal market proofs", "groth16 receipts", "zkVerify attestations"],
});

export const revalidate = 60;

type ProofSearchParams = {
  eventId?: string;
  event_id?: string;
  marketId?: string;
  market_id?: string;
  conditionId?: string;
  condition_id?: string;
  requestId?: string;
  request_id?: string;
};

export default async function ProofsPage({ searchParams }: { searchParams?: ProofSearchParams }) {
  const PAGE_SIZE = 24;
  const normalizedMarketId = searchParams?.marketId ?? searchParams?.market_id;
  const normalizedEventId = searchParams?.eventId ?? searchParams?.event_id;
  const normalizedConditionId = searchParams?.conditionId ?? searchParams?.condition_id;
  const normalizedRequestId = searchParams?.requestId ?? searchParams?.request_id;
  const filters = {
    eventId: normalizedEventId,
    conditionId: normalizedConditionId,
    requestId: normalizedRequestId,
    marketId: normalizedMarketId ? Number(normalizedMarketId) : undefined,
  };
  const { receipts, error } = await fetchProofReceipts(PAGE_SIZE, filters);
  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Proof receipts", path: "/proofs" },
  ]);
  return (
    <>
      <div className="mx-auto max-w-5xl px-4 py-16">
        <div className="space-y-4">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-400">Proof viewer</p>
          <h1 className="text-4xl font-semibold text-white">Groth16 receipts & zk attestations</h1>
          <p className="text-lg text-slate-300">
            Every settlement emits a replay-protected nonce, the market address, and zk proof metadata. Use this dashboard
            to cross-check on-chain verification with zkVerify receipts and downstream attestations.
          </p>
        </div>
        {error ? (
          <div className="mt-10 rounded-3xl border border-rose-400/30 bg-rose-500/10 p-6 text-center text-rose-100">
            <p className="text-lg font-semibold text-white">Unable to load proof receipts</p>
            <p className="mt-2 text-sm">The prover API responded with an error: {error}. Please retry in a moment.</p>
          </div>
        ) : (
          <div className="mt-10">
            <ProofsClient initialReceipts={receipts} pageSize={PAGE_SIZE} filters={filters} />
          </div>
        )}
      </div>
      <JsonLd data={breadcrumbs} id="proofs-breadcrumbs" />
    </>
  );
}
