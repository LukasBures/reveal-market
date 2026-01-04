"use client";

import { useCallback, useEffect, useRef, useState, useTransition } from "react";
import type { ProofReceipt } from "@/lib/api-types";
import { formatNumber } from "@/lib/formatters";
import { logger } from "@/lib/logging";
import { ProofReceiptList } from "./ProofReceiptList";

type Props = {
  initialReceipts: ProofReceipt[];
  pageSize?: number;
  filters?: {
    marketId?: number;
    eventId?: string;
    conditionId?: string;
    requestId?: string;
  };
};

async function fetchNextReceipts(
  limit: number,
  offset: number,
  filters?: Props["filters"],
): Promise<ProofReceipt[]> {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (offset > 0) {
    params.set("offset", String(offset));
  }
  if (filters?.marketId) {
    params.set("market_id", String(filters.marketId));
  }
  if (filters?.eventId) {
    params.set("event_id", filters.eventId);
  }
  if (filters?.conditionId) {
    params.set("condition_id", filters.conditionId);
  }
  if (filters?.requestId) {
    params.set("request_id", filters.requestId);
  }
  const response = await fetch(`/api/proofs?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to fetch proof receipts (${response.status})`);
  }
  const payload = await response.json();
  if (Array.isArray(payload)) {
    return payload as ProofReceipt[];
  }
  if (Array.isArray(payload?.data)) {
    return payload.data as ProofReceipt[];
  }
  return [];
}

export function ProofsClient({ initialReceipts, pageSize = 24, filters }: Props) {
  const [receipts, setReceipts] = useState(initialReceipts);
  const [hasMore, setHasMore] = useState(initialReceipts.length >= pageSize);
  const [isPending, startTransition] = useTransition();
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const offsetRef = useRef(initialReceipts.length);
  const filtersRef = useRef(filters);

  useEffect(() => {
    filtersRef.current = filters;
    setReceipts(initialReceipts);
    setHasMore(initialReceipts.length >= pageSize);
    offsetRef.current = initialReceipts.length;
  }, [filters, initialReceipts, pageSize]);

  const loadMore = useCallback(() => {
    if (!hasMore || isPending) {
      return;
    }
    startTransition(async () => {
      try {
        const next = await fetchNextReceipts(pageSize, offsetRef.current, filtersRef.current);
        if (!next.length) {
          setHasMore(false);
          return;
        }
        offsetRef.current += next.length;
        setReceipts((prev) => [...prev, ...next]);
        if (next.length < pageSize) {
          setHasMore(false);
        }
      } catch (error) {
        logger.clientError("ProofsClient:loadMore_failed", { error: (error as Error).message });
        setHasMore(false);
      }
    });
  }, [hasMore, isPending, pageSize]);

  useEffect(() => {
    const target = sentinelRef.current;
    if (!target || !hasMore) {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            observer.disconnect();
            loadMore();
            break;
          }
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMore, loadMore]);

  const proofReadyCount = receipts.filter((receipt) => Boolean(receipt.proofHash)).length;
  const uniqueMarkets = new Set(
    receipts
      .map((receipt) => receipt.marketAddress ?? receipt.marketId?.toString() ?? receipt.eventId ?? receipt.conditionId)
      .filter(Boolean),
  ).size;
  const filterChips = buildFilterChips(filters);

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-5 shadow-md shadow-black/30">
        <div className="grid gap-4 md:grid-cols-3">
          <SummaryMetric label="Receipts loaded" value={formatNumber(receipts.length)} />
          <SummaryMetric label="Proofs ready" value={formatNumber(proofReadyCount)} />
          <SummaryMetric label="Unique markets" value={formatNumber(uniqueMarkets)} />
        </div>
        {filterChips.length ? (
          <div className="mt-4 flex flex-wrap gap-2 text-xs text-slate-200">
            {filterChips.map((chip) => (
              <span key={chip.label} className="rounded-full border border-white/10 bg-white/5 px-3 py-1">
                <span className="text-slate-400">{chip.label}</span> {chip.value}
              </span>
            ))}
          </div>
        ) : (
          <p className="mt-4 text-xs text-slate-400">Values are shown in ZEN (18 decimals).</p>
        )}
      </div>
      <ProofReceiptList receipts={receipts} />
      <div ref={sentinelRef} aria-hidden className="h-6 w-full" />
      {hasMore ? (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={() => loadMore()}
            disabled={isPending}
            className="rounded-full border border-white/20 px-6 py-2 text-sm font-semibold text-white transition hover:border-brand-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {isPending ? "Loading…" : "Load more receipts"}
          </button>
        </div>
      ) : (
        <p className="text-center text-sm text-slate-400">
          All available proof receipts are loaded. Check back soon for fresh attestations.
        </p>
      )}
    </div>
  );
}

type SummaryMetricProps = {
  label: string;
  value: string;
};

function SummaryMetric({ label, value }: SummaryMetricProps) {
  return (
    <div className="rounded-xl border border-white/10 bg-black/30 px-4 py-3">
      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-white">{value}</p>
    </div>
  );
}

type FilterChip = {
  label: string;
  value: string;
};

function buildFilterChips(filters?: Props["filters"]): FilterChip[] {
  if (!filters) {
    return [];
  }
  const chips: FilterChip[] = [];
  if (filters.marketId) {
    chips.push({ label: "Market", value: String(filters.marketId) });
  }
  if (filters.eventId) {
    chips.push({ label: "Event", value: filters.eventId });
  }
  if (filters.conditionId) {
    chips.push({ label: "Condition", value: filters.conditionId });
  }
  if (filters.requestId) {
    chips.push({ label: "Request", value: filters.requestId });
  }
  return chips;
}
