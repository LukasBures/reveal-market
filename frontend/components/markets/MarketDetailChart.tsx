"use client";

import { useMemo } from "react";
import { usePriceStream } from "@/hooks/usePriceStream";

type Props = {
  marketId: string;
};

export function MarketDetailChart({ marketId }: Props) {
  const { history, error } = usePriceStream(marketId, 0);
  const hasStaleFx = history.some((p) => p.fx_stale);

  const pathData = useMemo(() => {
    if (history.length < 2) return "";
    const xs = history.map((p) => p.x);
    const ys = history.map((p) => p.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const width = maxX - minX || 1;
    const height = maxY - minY || 1;
    const normalize = (x: number, y: number) => [
      ((x - minX) / width) * 100,
      100 - ((y - minY) / height) * 100,
    ];
    const [firstX, firstY] = normalize(xs[0], ys[0]);
    let d = `M ${firstX},${firstY}`;
    for (let i = 1; i < history.length; i++) {
      const [nx, ny] = normalize(xs[i], ys[i]);
      d += ` L ${nx},${ny}`;
    }
    return d;
  }, [history]);

  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/50 p-6">
      <div className="flex items-center justify-between text-sm text-slate-400">
        <span>Price history</span>
        <span className="text-xs uppercase tracking-[0.2em] text-slate-500">
          {hasStaleFx ? "FX stale" : "Live"}
        </span>
      </div>
      <div className="mt-4 h-60 rounded-2xl bg-slate-950/80">
        {history.length >= 2 ? (
          <svg viewBox="0 0 100 100" className="h-full w-full">
            <defs>
              <linearGradient id="chart-fill" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.4" />
                <stop offset="100%" stopColor="#0f172a" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d={`${pathData} V 100 H 0 Z`} fill="url(#chart-fill)" />
            <path d={pathData} stroke="#22d3ee" strokeWidth="1.5" fill="none" />
          </svg>
        ) : (
          <div className="flex h-full items-center justify-center text-slate-500">
            {error ? `No data: ${error}` : "Waiting for live prices..."}
          </div>
        )}
      </div>
    </div>
  );
}
