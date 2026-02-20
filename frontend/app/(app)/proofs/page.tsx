import type { Metadata } from "next";

import Link from "next/link";
import dynamic from "next/dynamic";
import { fetchProofReceipts } from "@/lib/api";
import { buildBreadcrumbJsonLd, buildMetadata } from "@/lib/seo";
import { JsonLd } from "@/components/seo/JsonLd";

const ProofsClient = dynamic(
  () => import("@/components/proofs/ProofsClient").then((mod) => ({ default: mod.ProofsClient })),
  {
    loading: () => (
      <div className="rounded-3xl border border-white/10 bg-slate-950/40 p-6 text-center text-slate-300">
        Loading proof receipts...
      </div>
    ),
  },
);

export const metadata: Metadata = buildMetadata({
  title: "Proof Receipts | Reveal Market",
  description: "Browse settlement receipts for resolved prediction markets and verify outcomes at a glance.",
  path: "/proofs",
  keywords: ["reveal market proofs", "settlement receipts", "prediction market outcomes", "private prediction markets"],
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

export default async function ProofsPage({
  searchParams,
}: {
  searchParams?: Promise<ProofSearchParams | undefined>;
}) {
  const resolvedSearchParams = await searchParams;
  const PAGE_SIZE = 24;
  const normalizedMarketId = resolvedSearchParams?.marketId ?? resolvedSearchParams?.market_id;
  const normalizedEventId = resolvedSearchParams?.eventId ?? resolvedSearchParams?.event_id;
  const normalizedConditionId = resolvedSearchParams?.conditionId ?? resolvedSearchParams?.condition_id;
  const normalizedRequestId = resolvedSearchParams?.requestId ?? resolvedSearchParams?.request_id;
  const parsedMarketId = normalizedMarketId ? Number.parseInt(normalizedMarketId, 10) : undefined;
  const safeMarketId =
    parsedMarketId !== undefined &&
    Number.isFinite(parsedMarketId) &&
    Number.isSafeInteger(parsedMarketId) &&
    parsedMarketId > 0
      ? parsedMarketId
      : undefined;
  const filters = {
    eventId: normalizedEventId,
    conditionId: normalizedConditionId,
    requestId: normalizedRequestId,
    marketId: safeMarketId,
  };
  const { receipts, error } = await fetchProofReceipts(PAGE_SIZE, filters);
  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Proof receipts", path: "/proofs" },
  ]);
  return (
    <>
      <div className="mx-auto max-w-7xl px-4 py-12 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] sm:py-16">
        <div className="space-y-3">
          <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Proof ledger</p>
          <h1 className="text-3xl font-semibold text-white sm:text-4xl">Settlement proofs & receipt ledger</h1>
          <p className="text-base text-slate-300 sm:text-lg">
            Every resolved market publishes a receipt that shows the outcome and payout summary. Filter by market or
            request id to verify what was paid. Amounts are displayed in ZEN (18 decimals).
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
      <div className="mx-auto max-w-7xl px-4 pb-12 text-sm text-slate-300 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] sm:pb-16">
        Need help verifying an outcome?{" "}
        <Link href="/contact" className="text-brand-300 underline">
          Contact the team
        </Link>
        .
      </div>
      <JsonLd data={breadcrumbs} id="proofs-breadcrumbs" />
    </>
  );
}
