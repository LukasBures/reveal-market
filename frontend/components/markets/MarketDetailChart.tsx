"use client";

import { useEffect, useMemo, useState } from "react";
import { usePriceStream } from "@/hooks/usePriceStream";
import { usePriceStreamStore } from "@/hooks/usePriceStreamConnection";
import { formatTime } from "@/lib/formatters";
import { MarketFomoOverlay } from "./MarketFomoOverlay";

type Props = {
  marketId: string;
  tokenIds?: string[];
  outcomePrices?: number[];
};

export function MarketDetailChart({ marketId, tokenIds = [], outcomePrices = [] }: Props) {
  const [range, setRange] = useState<"1H" | "24H" | "7D" | "MAX">("24H");
  const selectedOutcome = 0;
  const { history, error } = usePriceStream(marketId, selectedOutcome, tokenIds);
  const streamState = usePriceStreamStore(marketId, tokenIds);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [fallbackHistory, setFallbackHistory] = useState<
    Array<{ x: number; y: number; fx_stale?: boolean; timestamp: string }>
  >([]);
  const normalizedPrices = useMemo(() => (Array.isArray(outcomePrices) ? outcomePrices : []), [outcomePrices]);
  const fallbackPrice =
    typeof normalizedPrices[selectedOutcome] === "number" && Number.isFinite(normalizedPrices[selectedOutcome])
      ? normalizedPrices[selectedOutcome]
      : null;

  const outcomeState = streamState.outcomes[selectedOutcome] ?? {};
  const liveStreamPrice =
    typeof outcomeState.displayPrice === "number" && Number.isFinite(outcomeState.displayPrice)
      ? outcomeState.displayPrice
      : typeof outcomeState.price === "number" && Number.isFinite(outcomeState.price)
        ? outcomeState.price
        : null;
  const liveStreamMid =
    typeof outcomeState.bestBid === "number" &&
    typeof outcomeState.bestAsk === "number" &&
    Number.isFinite(outcomeState.bestBid) &&
    Number.isFinite(outcomeState.bestAsk)
      ? (outcomeState.bestBid + outcomeState.bestAsk) / 2
      : null;
  const fallbackSeed = liveStreamPrice ?? liveStreamMid ?? fallbackPrice;
  useEffect(() => {
    if (history.length >= 2 || fallbackSeed === null) {
      setFallbackHistory((prev) => (prev.length ? [] : prev));
      return;
    }
    const now = Date.now();
    setFallbackHistory((prev) => {
      const last = prev[prev.length - 1];
      const minIntervalMs = 15_000;
      if (!prev.length) {
        const startTs = now - 5 * 60 * 1000;
        return [
          { x: startTs, y: fallbackSeed, fx_stale: streamState.fxStale, timestamp: new Date(startTs).toISOString() },
          { x: now, y: fallbackSeed, fx_stale: streamState.fxStale, timestamp: new Date(now).toISOString() },
        ];
      }
      if (last && Math.abs(last.y - fallbackSeed) < 1e-6 && now - last.x < minIntervalMs) {
        return prev;
      }
      return [
        ...prev.slice(-199),
        { x: now, y: fallbackSeed, fx_stale: streamState.fxStale, timestamp: new Date(now).toISOString() },
      ];
    });
  }, [history.length, fallbackSeed, streamState.fxStale, streamState.lastUpdated]);

  const displayHistory = history.length >= 2 ? history : fallbackHistory;
  const hasStaleFx = displayHistory.some((p) => p.fx_stale);
  const latestTs = displayHistory.length ? displayHistory[displayHistory.length - 1].timestamp : null;

  const filteredHistory = useMemo(() => {
    if (displayHistory.length === 0) return displayHistory;
    if (range === "MAX") return displayHistory;
    const now = displayHistory[displayHistory.length - 1].x;
    const windowMs =
      range === "1H" ? 60 * 60 * 1000 : range === "24H" ? 24 * 60 * 60 * 1000 : 7 * 24 * 60 * 60 * 1000;
    const cutoff = now - windowMs;
    const sliced = displayHistory.filter((p) => p.x >= cutoff);
    return sliced.length >= 2 ? sliced : displayHistory;
  }, [displayHistory, range]);

  const latestPrice = filteredHistory.length ? filteredHistory[filteredHistory.length - 1].y : null;
  const firstPrice = filteredHistory.length ? filteredHistory[0].y : null;
  const changePct =
    latestPrice !== null && firstPrice !== null && firstPrice > 0
      ? ((latestPrice - firstPrice) / firstPrice) * 100
      : null;

  const { pathData, areaData, minY, maxY, normalizedPoints } = useMemo(() => {
    if (filteredHistory.length < 2) {
      return {
        pathData: "",
        areaData: "",
        minY: null,
        maxY: null,
        normalizedPoints: [] as Array<{ xPct: number; yPct: number }>,
      };
    }
    const xs = filteredHistory.map((p) => p.x);
    const ys = filteredHistory.map((p) => p.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    let minY = Math.min(...ys);
    let maxY = Math.max(...ys);
    if (minY === maxY) {
      const padding = Math.max(Math.abs(minY) * 0.02, 0.01);
      minY -= padding;
      maxY += padding;
    }
    const width = maxX - minX || 1;
    const height = maxY - minY || 1;
    const normalizedPoints = filteredHistory.map((point) => ({
      xPct: ((point.x - minX) / width) * 100,
      yPct: 100 - ((point.y - minY) / height) * 100,
    }));
    const [first] = normalizedPoints;
    let d = `M ${first.xPct},${first.yPct}`;
    for (let i = 1; i < normalizedPoints.length; i++) {
      const point = normalizedPoints[i];
      d += ` L ${point.xPct},${point.yPct}`;
    }
    return {
      pathData: d,
      areaData: `${d} L 100,100 L 0,100 Z`,
      minY,
      maxY,
      normalizedPoints,
    };
  }, [filteredHistory]);

  const activeIndex =
    hoverIndex !== null && filteredHistory[hoverIndex] ? hoverIndex : Math.max(filteredHistory.length - 1, 0);
  const activePoint = filteredHistory[activeIndex];
  const activeNormalized = normalizedPoints[activeIndex];

  const parseNum = (value: any) => (typeof value === "number" && Number.isFinite(value) ? value : undefined);
  const bestBid = parseNum(outcomeState.bestBid);
  const bestAsk = parseNum(outcomeState.bestAsk);
  const spread =
    bestBid !== undefined && bestAsk !== undefined && Number.isFinite(bestAsk - bestBid)
      ? bestAsk - bestBid
      : undefined;
  const tickSize =
    typeof streamState.tickSize === "number"
      ? streamState.tickSize
      : undefined;

  const mapYToSvg = (value: number) => {
    if (minY === null || maxY === null) return null;
    const height = maxY - minY || 1;
    return 100 - ((value - minY) / height) * 100;
  };
  const bidY = bestBid !== undefined ? mapYToSvg(bestBid) : null;
  const askY = bestAsk !== undefined ? mapYToSvg(bestAsk) : null;
  const coverageMs =
    filteredHistory.length > 1 ? filteredHistory[filteredHistory.length - 1].x - filteredHistory[0].x : 0;

  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/50 p-6">
      <div className="flex flex-col gap-3 text-sm text-slate-200">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-baseline gap-3">
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
            {tickSize !== undefined && (
              <span className="rounded-full bg-white/10 px-3 py-1 text-[11px] uppercase tracking-[0.2em] text-white/70">
                Tick {tickSize}
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
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs uppercase tracking-[0.2em] text-slate-500">
          <span className="rounded-full bg-white/5 px-3 py-1">
            {hasStaleFx ? "FX stale" : "Live"} {latestTs ? `· ${formatTime(latestTs)}` : ""}
          </span>
          <div className="flex items-center gap-2 text-[11px]">
            <span className="rounded-full bg-white/5 px-3 py-1 text-white/70">
              Bid {bestBid !== undefined ? bestBid.toFixed(3) : "—"}
            </span>
            <span className="rounded-full bg-white/5 px-3 py-1 text-white/70">
              Ask {bestAsk !== undefined ? bestAsk.toFixed(3) : "—"}
            </span>
            <span className="rounded-full bg-white/5 px-3 py-1 text-white/70">
              Spread {spread !== undefined ? spread.toFixed(3) : "—"}
            </span>
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
              if (!normalizedPoints.length) return;
              const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
              const xPct = ((e.clientX - rect.left) / rect.width) * 100;
              let closest = 0;
              let closestDiff = Infinity;
              normalizedPoints.forEach((point, idx) => {
                const diff = Math.abs(point.xPct - xPct);
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
            {bidY !== null && askY !== null && (
              <rect
                x="0"
                width="100"
                y={Math.min(bidY, askY)}
                height={Math.max(1, Math.abs(askY - bidY))}
                fill="url(#chart-fill)"
                opacity="0.35"
              />
            )}
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
            {activePoint && activeNormalized && (
              <>
                <circle
                  cx={activeNormalized.xPct}
                  cy={activeNormalized.yPct}
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
      {(activePoint || coverageMs > 0) && (
        <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-300">
          {activePoint && (
            <>
              <span className="rounded-full bg-white/5 px-3 py-1">
                {formatTime(activePoint.timestamp)}
              </span>
              <span className="rounded-full bg-emerald-500/15 px-3 py-1 text-emerald-100">
                {activePoint.y.toFixed(4)} ZEN
              </span>
              {activePoint.fx_stale && (
                <span className="rounded-full bg-amber-500/15 px-3 py-1 text-amber-100">FX stale</span>
              )}
            </>
          )}
          {coverageMs > 0 && (
            <span className="rounded-full bg-white/5 px-3 py-1 text-white/70">
              Coverage ~
              {coverageMs >= 86_400_000
                ? `${(coverageMs / 86_400_000).toFixed(1)}d`
                : `${(coverageMs / 3_600_000).toFixed(1)}h`}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
