"use client";

import { useEffect, useMemo, useState } from "react";
import { usePriceStream, type PriceHistoryRange } from "@/hooks/usePriceStream";
import { usePriceStreamStore } from "@/hooks/usePriceStreamConnection";
import { formatTime } from "@/lib/formatters";
import { MarketFomoOverlay } from "./MarketFomoOverlay";

type Props = {
  marketId: string;
  tokenIds?: string[];
  outcomePrices?: number[];
  outcomes?: string[];
  initialOutcome?: number;
};

export function MarketDetailChart({
  marketId,
  tokenIds = [],
  outcomePrices = [],
  outcomes = [],
  initialOutcome = 0,
}: Props) {
  const [range, setRange] = useState<PriceHistoryRange>("24H");
  const [selectedOutcome, setSelectedOutcome] = useState(0);
  useEffect(() => {
    if (typeof initialOutcome === "number" && Number.isFinite(initialOutcome)) {
      setSelectedOutcome(Math.max(0, Math.min(initialOutcome, Math.max(outcomes.length - 1, 0))));
    }
  }, [initialOutcome, outcomes.length]);
  const { history, error } = usePriceStream(marketId, selectedOutcome, tokenIds, range);
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

  const chartPadding = { top: 6, right: 6, bottom: 14, left: 10 };
  const chartBox = useMemo(() => {
    const width = 100 - chartPadding.left - chartPadding.right;
    const height = 100 - chartPadding.top - chartPadding.bottom;
    return {
      left: chartPadding.left,
      right: 100 - chartPadding.right,
      top: chartPadding.top,
      bottom: 100 - chartPadding.bottom,
      width,
      height,
    };
  }, []);

  const { pathData, areaData, minY, maxY, normalizedPoints } = useMemo(() => {
    if (filteredHistory.length < 2) {
      return {
        pathData: "",
        areaData: "",
        minY: null,
        maxY: null,
        normalizedPoints: [] as Array<{ x: number; y: number }>,
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
      x: chartBox.left + ((point.x - minX) / width) * chartBox.width,
      y: chartBox.top + (1 - (point.y - minY) / height) * chartBox.height,
    }));
    const [first] = normalizedPoints;
    let d = `M ${first.x},${first.y}`;
    for (let i = 1; i < normalizedPoints.length; i++) {
      const point = normalizedPoints[i];
      d += ` L ${point.x},${point.y}`;
    }
    return {
      pathData: d,
      areaData: `${d} L ${chartBox.right},${chartBox.bottom} L ${chartBox.left},${chartBox.bottom} Z`,
      minY,
      maxY,
      normalizedPoints,
    };
  }, [filteredHistory, chartBox]);

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
    return chartBox.top + (1 - (value - minY) / height) * chartBox.height;
  };
  const bidY = bestBid !== undefined ? mapYToSvg(bestBid) : null;
  const askY = bestAsk !== undefined ? mapYToSvg(bestAsk) : null;
  const coverageMs =
    filteredHistory.length > 1 ? filteredHistory[filteredHistory.length - 1].x - filteredHistory[0].x : 0;

  const outcomeOptions = outcomes.length ? outcomes : [];
  const canSelectOutcome = outcomeOptions.length > 1;
  const yTicks = useMemo(() => {
    if (minY === null || maxY === null) return [];
    if (outcomeOptions.length) {
      const count = outcomeOptions.length;
      if (count === 1) {
        const y = chartBox.top + chartBox.height / 2;
        return [{ label: outcomeOptions[0], y }];
      }
      return outcomeOptions.map((label, idx) => {
        const ratio = count === 1 ? 0.5 : 1 - idx / (count - 1);
        return {
          label,
          y: chartBox.top + ratio * chartBox.height,
        };
      });
    }
    const ticks = 4;
    const step = (maxY - minY) / ticks;
    return Array.from({ length: ticks + 1 }, (_, idx) => {
      const value = minY + step * idx;
      return {
        label: value.toFixed(3),
        y: mapYToSvg(value),
      };
    }).filter((tick) => tick.y !== null) as Array<{ label: string; y: number }>;
  }, [minY, maxY, outcomeOptions, chartBox]);

  const xTicks = useMemo(() => {
    if (filteredHistory.length < 2) return [];
    const start = filteredHistory[0];
    const end = filteredHistory[filteredHistory.length - 1];
    const mid = filteredHistory[Math.floor(filteredHistory.length / 2)];
    return [
      { label: formatTime(start.timestamp), x: chartBox.left },
      { label: formatTime(mid.timestamp), x: chartBox.left + chartBox.width / 2 },
      { label: formatTime(end.timestamp), x: chartBox.right },
    ];
  }, [filteredHistory, chartBox]);

  const hoverLabel = activePoint
    ? `${formatTime(activePoint.timestamp)} · ${activePoint.y.toFixed(4)} ZEN`
    : null;

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
            {canSelectOutcome &&
              outcomeOptions.map((option, idx) => (
                <button
                  key={`${option}-${idx}`}
                  type="button"
                  onClick={() => setSelectedOutcome(idx)}
                  className={`rounded-full px-3 py-1 text-[11px] uppercase tracking-[0.2em] ${
                    selectedOutcome === idx
                      ? "bg-emerald-400 text-slate-900"
                      : "bg-white/10 text-white/80 hover:bg-white/20"
                  }`}
                >
                  {option}
                </button>
              ))}
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
              const clampedX = Math.min(Math.max(xPct, chartBox.left), chartBox.right);
              let closest = 0;
              let closestDiff = Infinity;
              normalizedPoints.forEach((point, idx) => {
                const diff = Math.abs(point.x - clampedX);
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
            <g>
              {yTicks.map((tick) => (
                <g key={`y-${tick.label}`}>
                  <line
                    x1={chartBox.left}
                    x2={chartBox.right}
                    y1={tick.y}
                    y2={tick.y}
                    stroke="rgba(148,163,184,0.15)"
                    strokeDasharray="2 3"
                  />
                  <text
                    x={chartBox.left - 2}
                    y={tick.y}
                    textAnchor="end"
                    dominantBaseline="middle"
                    fill="rgba(148,163,184,0.7)"
                    fontSize="3"
                  >
                    {tick.label}
                  </text>
                </g>
              ))}
              {xTicks.map((tick) => (
                <text
                  key={`x-${tick.label}`}
                  x={tick.x}
                  y={chartBox.bottom + 6}
                  textAnchor={tick.x === chartBox.left ? "start" : tick.x === chartBox.right ? "end" : "middle"}
                  fill="rgba(148,163,184,0.7)"
                  fontSize="3"
                >
                  {tick.label}
                </text>
              ))}
            </g>
            {bidY !== null && askY !== null && (
              <rect
                x={chartBox.left}
                width={chartBox.width}
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
                <line
                  x1={activeNormalized.x}
                  x2={activeNormalized.x}
                  y1={chartBox.top}
                  y2={chartBox.bottom}
                  stroke="rgba(226,232,240,0.3)"
                  strokeDasharray="2 3"
                />
                <circle
                  cx={activeNormalized.x}
                  cy={activeNormalized.y}
                  r="2.2"
                  fill="#34d399"
                  stroke="#fff"
                  strokeWidth="0.4"
                />
                {hoverLabel && (
                  <g>
                    <rect
                      x={Math.min(Math.max(activeNormalized.x - 18, chartBox.left), chartBox.right - 36)}
                      y={chartBox.top + 1}
                      width="36"
                      height="8"
                      rx="2"
                      fill="rgba(15,23,42,0.85)"
                      stroke="rgba(148,163,184,0.4)"
                      strokeWidth="0.3"
                    />
                    <text
                      x={Math.min(Math.max(activeNormalized.x - 18, chartBox.left), chartBox.right - 36) + 18}
                      y={chartBox.top + 6}
                      textAnchor="middle"
                      fill="rgba(226,232,240,0.9)"
                      fontSize="3"
                    >
                      {hoverLabel}
                    </text>
                  </g>
                )}
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
