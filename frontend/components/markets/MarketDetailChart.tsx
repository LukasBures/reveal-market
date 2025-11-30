"use client";

import { useMemo, useState } from "react";
import { usePriceStream } from "@/hooks/usePriceStream";
import { MarketFomoOverlay } from "./MarketFomoOverlay";

type Props = {
  marketId: string;
  tokenIds?: string[];
  outcomes?: string[];
};

export function MarketDetailChart({ marketId, tokenIds = [], outcomes = [] }: Props) {
  const [range, setRange] = useState<"1H" | "24H" | "7D" | "MAX">("24H");
  const [selectedOutcome, setSelectedOutcome] = useState<number>(0);
  const { history, error } = usePriceStream(marketId, selectedOutcome, tokenIds);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const hasStaleFx = history.some((p) => p.fx_stale);
  const latestTs = history.length ? history[history.length - 1].timestamp : null;

  const filteredHistory = useMemo(() => {
    if (history.length === 0) return history;
    if (range === "MAX") return history;
    const now = history[history.length - 1].x;
    const windowMs =
      range === "1H" ? 60 * 60 * 1000 : range === "24H" ? 24 * 60 * 60 * 1000 : 7 * 24 * 60 * 60 * 1000;
    const cutoff = now - windowMs;
    const sliced = history.filter((p) => p.x >= cutoff);
    return sliced.length >= 2 ? sliced : history;
  }, [history, range]);

  const latestPrice = filteredHistory.length ? filteredHistory[filteredHistory.length - 1].y : null;
  const firstPrice = filteredHistory.length ? filteredHistory[0].y : null;
  const changePct =
    latestPrice !== null && firstPrice !== null && firstPrice > 0
      ? ((latestPrice - firstPrice) / firstPrice) * 100
      : null;

  const { pathData, areaData } = useMemo(() => {
    if (filteredHistory.length < 2) return { pathData: "", areaData: "" };
    const xs = filteredHistory.map((p) => p.x);
    const ys = filteredHistory.map((p) => p.y);
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
    for (let i = 1; i < filteredHistory.length; i++) {
      const [nx, ny] = normalize(xs[i], ys[i]);
      d += ` L ${nx},${ny}`;
    }
    return {
      pathData: d,
      areaData: `${d} L 100,100 L 0,100 Z`,
    };
  }, [filteredHistory]);

  const activePoint =
    hoverIndex !== null && filteredHistory[hoverIndex]
      ? filteredHistory[hoverIndex]
      : filteredHistory[filteredHistory.length - 1];

  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/50 p-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between text-sm text-slate-200">
        <div className="flex items-baseline gap-3">
          <span className="text-xs uppercase tracking-[0.2em] text-slate-500">Price history</span>
          <span className="text-2xl font-semibold text-white">
            {latestPrice !== null ? latestPrice.toFixed(3) : "—"} ZEN
          </span>
          {changePct !== null && (
            <span
              className={`text-sm font-semibold ${
                changePct >= 0 ? "text-emerald-300" : "text-rose-300"
              }`}
            >
              {changePct >= 0 ? "+" : ""}
              {changePct.toFixed(2)}%
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {(["1H", "24H", "7D", "MAX"] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setRange(option)}
              className={`rounded-full px-3 py-1 text-[11px] uppercase tracking-[0.2em] ${
                range === option ? "bg-white text-slate-900" : "bg-white/10 text-white/80 hover:bg-white/20"
              }`}
            >
              {option}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.2em] text-slate-500">
          <span className="rounded-full bg-white/5 px-3 py-1">
            {hasStaleFx ? "FX stale" : "Live"} {latestTs ? `· ${new Date(latestTs).toLocaleTimeString()}` : ""}
          </span>
          <div className="flex flex-wrap gap-2">
            {(outcomes.length ? outcomes : ["Outcome 1", "Outcome 2"]).slice(0, Math.max(2, outcomes.length || 2)).map((label, idx) => (
              <button
                key={`${label}-${idx}`}
                type="button"
                onClick={() => setSelectedOutcome(idx)}
                className={`rounded-full px-3 py-1 ${
                  selectedOutcome === idx ? "bg-white text-slate-900" : "bg-white/10 text-white/80 hover:bg-white/20"
                }`}
              >
                {label || `Outcome ${idx + 1}`}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="relative mt-4 h-64 rounded-2xl bg-gradient-to-b from-slate-900/90 via-slate-950/90 to-black/90 p-4 shadow-inner shadow-black/40">
        <MarketFomoOverlay marketId={marketId} tokenIds={tokenIds} />
        {filteredHistory.length >= 2 ? (
          <svg
            viewBox="0 0 100 100"
            className="h-full w-full"
            onMouseLeave={() => setHoverIndex(null)}
            onMouseMove={(e) => {
              const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
              const xPct = ((e.clientX - rect.left) / rect.width) * 100;
              // find closest point by normalized x
              let closest = 0;
              let closestDiff = Infinity;
              filteredHistory.forEach((pt, idx) => {
                const xs = filteredHistory.map((p) => p.x);
                const minX = Math.min(...xs);
                const maxX = Math.max(...xs);
                const width = maxX - minX || 1;
                const normX = ((pt.x - minX) / width) * 100;
                const diff = Math.abs(normX - xPct);
                if (diff < closestDiff) {
                  closestDiff = diff;
                  closest = idx;
                }
              });
              setHoverIndex(closest);
            }}
          >
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
            {activePoint && (
              <>
                <circle
                  cx={
                    (() => {
                      const xs = filteredHistory.map((p) => p.x);
                      const minX = Math.min(...xs);
                      const maxX = Math.max(...xs);
                      const width = maxX - minX || 1;
                      return ((activePoint.x - minX) / width) * 100;
                    })()
                  }
                  cy={
                    (() => {
                      const ys = filteredHistory.map((p) => p.y);
                      const minY = Math.min(...ys);
                      const maxY = Math.max(...ys);
                      const height = maxY - minY || 1;
                      return 100 - ((activePoint.y - minY) / height) * 100;
                    })()
                  }
                  r="2.2"
                  fill="#34d399"
                  stroke="#fff"
                  strokeWidth="0.4"
                />
              </>
            )}
          </svg>
        ) : (
          <div className="flex h-full items-center justify-center text-slate-500">
            {error ? `No data: ${error}` : "Waiting for live prices..."}
          </div>
        )}
      </div>
      {activePoint && (
        <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-300">
          <span className="rounded-full bg-white/5 px-3 py-1">
            {new Date(activePoint.timestamp).toLocaleTimeString()}
          </span>
          <span className="rounded-full bg-emerald-500/15 px-3 py-1 text-emerald-100">
            {activePoint.y.toFixed(4)} ZEN
          </span>
          {activePoint.fx_stale && (
            <span className="rounded-full bg-amber-500/15 px-3 py-1 text-amber-100">FX stale</span>
          )}
        </div>
      )}
    </div>
  );
}
