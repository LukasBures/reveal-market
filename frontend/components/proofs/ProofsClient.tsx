"use client";

import { useCallback, useEffect, useRef, useState, useTransition } from "react";
import type { ProofReceipt } from "@/lib/api-types";
import { logger } from "@/lib/logging";
import { ProofReceiptList } from "./ProofReceiptList";

type Props = {
  initialReceipts: ProofReceipt[];
  pageSize?: number;
};

async function fetchNextReceipts(limit: number, offset: number): Promise<ProofReceipt[]> {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (offset > 0) {
    params.set("offset", String(offset));
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

export function ProofsClient({ initialReceipts, pageSize = 24 }: Props) {
  const [receipts, setReceipts] = useState(initialReceipts);
  const [hasMore, setHasMore] = useState(initialReceipts.length >= pageSize);
  const [isPending, startTransition] = useTransition();
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const offsetRef = useRef(initialReceipts.length);

  const loadMore = useCallback(
    (mode: "auto" | "manual" = "manual") => {
      if (!hasMore || isPending) {
        return;
      }
      startTransition(async () => {
        try {
          const next = await fetchNextReceipts(pageSize, offsetRef.current);
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
          logger.error("ProofsClient:loadMore_failed", { error: (error as Error).message });
          setHasMore(false);
        }
      });
    },
    [hasMore, isPending, pageSize],
  );

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
            loadMore("auto");
            break;
          }
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMore, loadMore]);

  return (
    <div className="space-y-6">
      <ProofReceiptList receipts={receipts} />
      <div ref={sentinelRef} aria-hidden className="h-6 w-full" />
      {hasMore ? (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={() => loadMore("manual")}
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
