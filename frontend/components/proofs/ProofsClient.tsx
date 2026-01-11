"use client";

import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { ProofReceipt } from "@/lib/api-types";
import { formatDateTime, formatNumber } from "@/lib/formatters";
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

type DraftFilters = {
  marketId: string;
  eventId: string;
  conditionId: string;
  requestId: string;
};

const EMPTY_FILTERS: DraftFilters = {
  marketId: "",
  eventId: "",
  conditionId: "",
  requestId: "",
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
  const [isLoadingMore, startLoadMore] = useTransition();
  const [isFiltering, startFilterTransition] = useTransition();
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const offsetRef = useRef(initialReceipts.length);
  const filtersRef = useRef(filters);
  const [draftFilters, setDraftFilters] = useState<DraftFilters>(() => buildDraftFilters(filters));
  const router = useRouter();

  useEffect(() => {
    filtersRef.current = filters;
    setReceipts(initialReceipts);
    setHasMore(initialReceipts.length >= pageSize);
    offsetRef.current = initialReceipts.length;
    setDraftFilters(buildDraftFilters(filters));
  }, [filters, initialReceipts, pageSize]);

  const loadMore = useCallback(() => {
    if (!hasMore || isLoadingMore) {
      return;
    }
    startLoadMore(async () => {
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
  }, [hasMore, isLoadingMore, pageSize, startLoadMore]);

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

  const { proofReadyCount, uniqueMarkets, latestReceipt } = useMemo(() => {
    let readyCount = 0;
    const markets = new Set<string>();
    let latestTimestamp: number | null = null;
    for (const receipt of receipts) {
      if (receipt.proofHash) {
        readyCount += 1;
      }
      const marketKey =
        receipt.marketAddress ?? receipt.marketId?.toString() ?? receipt.eventId ?? receipt.conditionId ?? null;
      if (marketKey) {
        markets.add(marketKey);
      }
      if (receipt.generatedAt) {
        const timestamp = new Date(receipt.generatedAt).getTime();
        if (!Number.isNaN(timestamp)) {
          latestTimestamp = latestTimestamp === null ? timestamp : Math.max(latestTimestamp, timestamp);
        }
      }
    }
    return {
      proofReadyCount: readyCount,
      uniqueMarkets: markets.size,
      latestReceipt: latestTimestamp !== null ? formatDateTime(new Date(latestTimestamp)) : "—",
    };
  }, [receipts]);
  const filterChips = useMemo(() => buildFilterChips(filters), [filters]);
  const hasDraftFilters = useMemo(
    () => Object.values(draftFilters).some((value) => value.trim().length > 0),
    [draftFilters],
  );

  const handleFilterSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const nextParams = buildFilterQuery(draftFilters);
      startFilterTransition(() => {
        router.push(nextParams ? `/proofs?${nextParams}` : "/proofs");
      });
    },
    [draftFilters, router, startFilterTransition],
  );

  const handleClearFilters = useCallback(() => {
    startFilterTransition(() => {
      setDraftFilters({ ...EMPTY_FILTERS });
      router.push("/proofs");
    });
  }, [router, startFilterTransition]);

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-5 shadow-md shadow-black/30">
        <div className="grid gap-4 md:grid-cols-4">
          <SummaryMetric label="Receipts loaded" value={formatNumber(receipts.length)} />
          <SummaryMetric label="Proofs ready" value={formatNumber(proofReadyCount)} />
          <SummaryMetric label="Unique markets" value={formatNumber(uniqueMarkets)} />
          <SummaryMetric label="Latest receipt" value={latestReceipt} />
        </div>
        <form onSubmit={handleFilterSubmit} className="mt-4 space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <FilterField
              label="Market id"
              value={draftFilters.marketId}
              placeholder="123"
              inputMode="numeric"
              onChange={(value) => setDraftFilters((prev) => ({ ...prev, marketId: value.replace(/[^\d]/g, "") }))}
            />
            <FilterField
              label="Event id"
              value={draftFilters.eventId}
              placeholder="mvp-lose-..."
              onChange={(value) => setDraftFilters((prev) => ({ ...prev, eventId: value }))}
            />
            <FilterField
              label="Condition id"
              value={draftFilters.conditionId}
              placeholder="0x..."
              onChange={(value) => setDraftFilters((prev) => ({ ...prev, conditionId: value }))}
            />
            <FilterField
              label="Request id"
              value={draftFilters.requestId}
              placeholder="req-..."
              onChange={(value) => setDraftFilters((prev) => ({ ...prev, requestId: value }))}
            />
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <button
              type="submit"
              disabled={isFiltering}
              className="rounded-full bg-brand-500 px-5 py-2 text-xs font-semibold uppercase tracking-[0.25em] text-white transition hover:bg-brand-400 disabled:opacity-40 sm:tracking-[0.3em]"
            >
              {isFiltering ? "Filtering…" : "Apply filters"}
            </button>
            <button
              type="button"
              onClick={handleClearFilters}
              disabled={!hasDraftFilters || isFiltering}
              className="rounded-full border border-white/15 bg-white/5 px-5 py-2 text-xs font-semibold uppercase tracking-[0.25em] text-white transition hover:border-white/40 disabled:opacity-40 sm:tracking-[0.3em]"
            >
              Clear
            </button>
            <span className="text-slate-400">Values are shown in ZEN (18 decimals).</span>
          </div>
        </form>
        {filterChips.length ? (
          <div className="mt-4 flex flex-wrap gap-2 text-xs text-slate-200">
            {filterChips.map((chip) => (
              <span key={chip.label} className="rounded-full border border-white/10 bg-white/5 px-3 py-1">
                <span className="text-slate-400">{chip.label}</span> {chip.value}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      <ProofReceiptList receipts={receipts} />
      <div ref={sentinelRef} aria-hidden className="h-6 w-full" />
      {hasMore ? (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={() => loadMore()}
            disabled={isLoadingMore}
            className="rounded-full border border-white/20 bg-white/5 px-6 py-2 text-sm font-semibold text-white transition hover:border-white/40 hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {isLoadingMore ? "Loading…" : "Load more receipts"}
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

function buildDraftFilters(filters?: Props["filters"]): DraftFilters {
  return {
    marketId: filters?.marketId ? String(filters.marketId) : "",
    eventId: filters?.eventId ?? "",
    conditionId: filters?.conditionId ?? "",
    requestId: filters?.requestId ?? "",
  };
}

function buildFilterQuery(filters: DraftFilters): string {
  const params = new URLSearchParams();
  const marketIdValue = filters.marketId.trim();
  if (marketIdValue) {
    const parsedMarket = Number(marketIdValue);
    if (Number.isFinite(parsedMarket) && parsedMarket > 0) {
      params.set("marketId", String(parsedMarket));
    }
  }
  const eventIdValue = filters.eventId.trim();
  if (eventIdValue) {
    params.set("eventId", eventIdValue);
  }
  const conditionIdValue = filters.conditionId.trim();
  if (conditionIdValue) {
    params.set("conditionId", conditionIdValue);
  }
  const requestIdValue = filters.requestId.trim();
  if (requestIdValue) {
    params.set("requestId", requestIdValue);
  }
  return params.toString();
}

type FilterFieldProps = {
  label: string;
  value: string;
  placeholder?: string;
  inputMode?: "text" | "numeric";
  onChange: (value: string) => void;
};

function FilterField({ label, value, placeholder, inputMode = "text", onChange }: FilterFieldProps) {
  const fieldId = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
  return (
    <label className="text-xs uppercase tracking-[0.3em] text-slate-400">
      {label}
      <input
        id={fieldId}
        name={fieldId}
        type="text"
        value={value}
        placeholder={placeholder}
        inputMode={inputMode}
        onChange={(event) => onChange(event.target.value)}
        className="mt-2 w-full rounded-xl border border-white/10 bg-black/40 px-4 py-2 text-sm text-white placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-brand-400/60"
      />
    </label>
  );
}
