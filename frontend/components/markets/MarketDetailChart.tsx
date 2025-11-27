"use client";

import { useMemo } from "react";
import { usePriceStream } from "@/hooks/usePriceStream";

type Props = {
  marketId: string;
  tokenIds?: string[];
};

export function MarketDetailChart({ marketId, tokenIds = [] }: Props) {
  const { history, error } = usePriceStream(marketId, 0, tokenIds);
  const hasStaleFx = history.some((p) => p.fx_stale);
  const latestTs = history.length ? history[history.length - 1].timestamp : null;

  const { pathData, areaData } = useMemo(() => {
    if (history.length < 2) return { pathData: "", areaData: "" };
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
    return {
      pathData: d,
      areaData: `${d} L 100,100 L 0,100 Z`,
    };
  }, [history]);

  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/50 p-6">
      <div className="flex items-center justify-between text-sm text-slate-400">
        <span>Price history</span>
        <span className="text-xs uppercase tracking-[0.2em] text-slate-500">
          {hasStaleFx ? "FX stale" : "Live"} {latestTs ? `· ${new Date(latestTs).toLocaleTimeString()}` : ""}
        </span>
      </div>
      <div className="mt-4 h-64 rounded-2xl bg-gradient-to-b from-slate-900/90 via-slate-950/90 to-black/90 p-4 shadow-inner shadow-black/40">
        {history.length >= 2 ? (
          <svg viewBox="0 0 100 100" className="h-full w-full">
            <defs>
              <linearGradient id="chart-fill" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="#34d399" stopOpacity="0.35" />
                <stop offset="100%" stopColor="#0f172a" stopOpacity="0" />
              </linearGradient>
              <linearGradient id="chart-line" x1="0" x2="1" y1="0" y2="0">
                <stop offset="0%" stopColor="#34d399" />
                <stop offset="100%" stopColor="#22d3ee" />
              </linearGradient>
            </defs>
            <path d={areaData} fill="url(#chart-fill)" />
            <path
              d={pathData}
              stroke="url(#chart-line)"
              strokeWidth="1.6"
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
              filter="url(#glow)"
            />
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
