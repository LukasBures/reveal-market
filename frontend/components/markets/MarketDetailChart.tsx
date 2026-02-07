"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { usePriceStream, type PriceHistoryRange } from "@/hooks/usePriceStream";
import { usePriceStreamStore } from "@/hooks/usePriceStreamConnection";
import { formatTime } from "@/lib/formatters";
import { MarketFomoOverlay } from "./MarketFomoOverlay";
import uPlot from "uplot";

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
  const [cursorPos, setCursorPos] = useState<{ x: number; y: number } | null>(null);
  const [chartSize, setChartSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 });
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

  const dataSeries = useMemo(() => {
    const xs = filteredHistory.map((p) => p.x);
    const ys = filteredHistory.map((p) => p.y);
    return [xs, ys];
  }, [filteredHistory]);

  const activeIndex =
    hoverIndex !== null && filteredHistory[hoverIndex] ? hoverIndex : Math.max(filteredHistory.length - 1, 0);
  const activePoint = filteredHistory[activeIndex];

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

  const coverageMs =
    filteredHistory.length > 1 ? filteredHistory[filteredHistory.length - 1].x - filteredHistory[0].x : 0;

  const outcomeOptions = useMemo(() => (outcomes.length ? outcomes : []), [outcomes]);
  const canSelectOutcome = outcomeOptions.length > 1;

  const chartRef = useRef<HTMLDivElement | null>(null);
  const plotRef = useRef<uPlot | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const plotKey = useMemo(() => outcomeOptions.join("|"), [outcomeOptions]);

  useEffect(() => {
    if (!chartRef.current) return;
    if (filteredHistory.length < 2) {
      if (plotRef.current) {
        plotRef.current.destroy();
        plotRef.current = null;
      }
      setCursorPos(null);
      return;
    }

    const container = chartRef.current;
    const basePadding = { top: 10, right: 10, bottom: 28, left: 42 };

    const formatAxisTime = (value: number) => formatTime(new Date(value));
    const formatOutcomeLabels = (values: number[]) => {
      if (outcomeOptions.length >= 2) {
        return values.map((_, idx) => {
          if (idx === 0) return outcomeOptions[outcomeOptions.length - 1] ?? "No";
          if (idx === values.length - 1) return outcomeOptions[0] ?? "Yes";
          return "";
        });
      }
      return values.map((value) => value.toFixed(3));
    };

    const options: uPlot.Options = {
      width: container.clientWidth,
      height: container.clientHeight,
      padding: [basePadding.top, basePadding.right, basePadding.bottom, basePadding.left],
      legend: { show: false },
      cursor: {
        focus: { prox: 30 },
        drag: { setScale: false },
      },
      scales: {
        x: {
          time: true,
        },
      },
      axes: [
        {
          stroke: "rgba(148,163,184,0.6)",
          grid: { stroke: "rgba(148,163,184,0.18)", width: 1 },
          values: (_u, vals) => vals.map((v) => formatAxisTime(v)),
        },
        {
          stroke: "rgba(148,163,184,0.6)",
          grid: { stroke: "rgba(148,163,184,0.14)", width: 1 },
          values: (_u, vals) => formatOutcomeLabels(vals),
        },
      ],
      series: [
        {},
        {
          label: "Price",
          stroke: "#34d399",
          width: 2,
          fill: "rgba(52,211,153,0.22)",
          points: { show: false },
        },
      ],
      hooks: {
        setCursor: [
          (u) => {
            if (typeof u.cursor.idx !== "number") {
              setHoverIndex(null);
              setCursorPos(null);
              return;
            }
            setHoverIndex(u.cursor.idx);
            if (typeof u.cursor.left === "number" && typeof u.cursor.top === "number") {
              setCursorPos({ x: u.cursor.left, y: u.cursor.top });
            }
          },
        ],
      },
    };

    if (plotRef.current) {
      plotRef.current.destroy();
      plotRef.current = null;
    }

    plotRef.current = new uPlot(options, dataSeries as uPlot.AlignedData, container);

    if (resizeObserverRef.current) {
      resizeObserverRef.current.disconnect();
    }
    const observer = new ResizeObserver(() => {
      if (!plotRef.current || !chartRef.current) return;
      setChartSize({ width: chartRef.current.clientWidth, height: chartRef.current.clientHeight });
      plotRef.current.setSize({
        width: chartRef.current.clientWidth,
        height: chartRef.current.clientHeight,
      });
    });
    observer.observe(container);
    resizeObserverRef.current = observer;
    setChartSize({ width: container.clientWidth, height: container.clientHeight });

    return () => {
      observer.disconnect();
    };
  }, [filteredHistory.length, plotKey, outcomeOptions, dataSeries]);

  useEffect(() => {
    if (!plotRef.current) return;
    plotRef.current.setData(dataSeries as uPlot.AlignedData);
  }, [dataSeries]);

  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/50 p-6">
      <div className="flex flex-col gap-3 text-sm text-slate-200">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-baseline gap-3">
            <span className="text-xs uppercase tracking-[0.2em] text-slate-500">Price history</span>
            <span className="text-2xl font-semibold text-white tabular-nums">
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
            <div className="flex items-center rounded-full border border-white/10 bg-white/5 p-1">
              {(["1H", "24H", "7D", "MAX"] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setRange(option)}
                  className={`rounded-full px-3 py-1 text-[11px] uppercase tracking-[0.2em] ${
                    range === option
                      ? "bg-white text-slate-900 shadow"
                      : "bg-transparent text-white/70 hover:text-white"
                  }`}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs uppercase tracking-[0.2em] text-slate-500">
            <span className="rounded-full bg-white/5 px-3 py-1 tabular-nums">
              {hasStaleFx ? "FX stale" : "Live"} {latestTs ? `· ${formatTime(latestTs)}` : ""}
            </span>
            <div className="flex items-center gap-2 text-[11px]">
              <span className="rounded-full bg-white/5 px-3 py-1 text-white/70 tabular-nums">
                Bid {bestBid !== undefined ? bestBid.toFixed(3) : "—"}
              </span>
              <span className="rounded-full bg-white/5 px-3 py-1 text-white/70 tabular-nums">
                Ask {bestAsk !== undefined ? bestAsk.toFixed(3) : "—"}
              </span>
              <span className="rounded-full bg-white/5 px-3 py-1 text-white/70 tabular-nums">
                Spread {spread !== undefined ? spread.toFixed(3) : "—"}
              </span>
            </div>
        </div>
      </div>
      <div className="relative mt-4 h-72 rounded-2xl bg-gradient-to-b from-slate-900/90 via-slate-950/90 to-black/90 p-2 shadow-inner shadow-black/40">
        <MarketFomoOverlay marketId={marketId} tokenIds={tokenIds} />
        {filteredHistory.length >= 2 ? (
          <div className="relative h-full w-full">
            <div ref={chartRef} className="market-chart h-full w-full" />
            {activePoint && (
              <div
                className="pointer-events-none absolute rounded-lg border border-white/10 bg-slate-900/85 px-3 py-1 text-[11px] text-slate-100 shadow-lg"
                style={{
                  left: Math.max(10, Math.min((cursorPos?.x ?? 0) - 60, chartSize.width - 150)),
                  top: Math.max(8, Math.min((cursorPos?.y ?? 0) - 34, chartSize.height - 40)),
                }}
              >
                {formatTime(activePoint.timestamp)} · {activePoint.y.toFixed(4)} ZEN
              </div>
            )}
          </div>
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
