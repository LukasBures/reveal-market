"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { usePriceStream, type PriceHistoryRange } from "@/hooks/usePriceStream";
import { seedHistory, usePriceStreamStore } from "@/hooks/usePriceStreamConnection";
import { fetchPriceHistory, type PriceHistoryInterval } from "@/lib/pricing-client";
import { formatTime } from "@/lib/formatters";
import { MarketFomoOverlay } from "./MarketFomoOverlay";
import uPlot from "uplot";

type Props = {
  marketId: string;
  tokenIds?: string[];
  outcomePrices?: number[];
  outcomes?: string[];
  initialOutcome?: number;
  selectedOutcome?: number;
};

export function MarketDetailChart({
  marketId,
  tokenIds = [],
  outcomePrices = [],
  outcomes = [],
  initialOutcome = 0,
  selectedOutcome: selectedOutcomeOverride,
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
  useEffect(() => {
    if (typeof selectedOutcomeOverride === "number" && Number.isFinite(selectedOutcomeOverride)) {
      setSelectedOutcome(Math.max(0, Math.min(selectedOutcomeOverride, Math.max(outcomes.length - 1, 0))));
    }
  }, [selectedOutcomeOverride, outcomes.length]);
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

  const outcomeOptions = useMemo(() => (outcomes.length ? outcomes : []), [outcomes]);
  const outcomeIndices = useMemo(
    () => (outcomeOptions.length ? outcomeOptions.map((_, idx) => idx) : [0]),
    [outcomeOptions],
  );

  const rangeConfig = useMemo(() => {
    const config: Record<PriceHistoryRange, { interval: PriceHistoryInterval; fidelity: number }> = {
      "1H": { interval: "1h", fidelity: 1 },
      "24H": { interval: "1d", fidelity: 5 },
      "7D": { interval: "1w", fidelity: 30 },
      "MAX": { interval: "max", fidelity: 240 },
    };
    return config[range] ?? config["24H"];
  }, [range]);

  useEffect(() => {
    let cancelled = false;
    const loadHistories = async () => {
      await Promise.all(
        outcomeIndices.map(async (idx) => {
          try {
            const tokenId = tokenIds[idx];
            const data = await fetchPriceHistory(marketId, idx, {
              interval: rangeConfig.interval,
              fidelity: rangeConfig.fidelity,
              tokenId,
            });
            if (cancelled) return;
            seedHistory(
              marketId,
              idx,
              data
                .map((entry) => ({
                  timestamp: entry.timestamp,
                  price: Number(entry.price),
                  display_price: Number(entry.display_price),
                  fx_stale: entry.fx_stale,
                }))
                .filter((p) => Number.isFinite(p.price)),
              tokenIds,
            );
          } catch {
            // best-effort; fall back to live stream or seed data already present
          }
        }),
      );
    };
    void loadHistories();
    return () => {
      cancelled = true;
    };
  }, [marketId, outcomeIndices, rangeConfig.interval, rangeConfig.fidelity, tokenIds]);

  const historiesByOutcome = useMemo(() => {
    return outcomeIndices.map((idx) =>
      (streamState.histories[idx] ?? []).map((point) => ({
        x: new Date(point.timestamp).getTime(),
        y: point.display_price || point.price,
        fx_stale: point.fx_stale,
        timestamp: point.timestamp,
      })),
    );
  }, [streamState.histories, outcomeIndices]);

  const maxTimestamp = useMemo(() => {
    const lastValues = historiesByOutcome
      .map((series) => (series.length ? series[series.length - 1].x : null))
      .filter((value): value is number => value !== null);
    if (!lastValues.length) return null;
    return Math.max(...lastValues);
  }, [historiesByOutcome]);

  const filteredHistories = useMemo(() => {
    if (!maxTimestamp) return historiesByOutcome;
    if (range === "MAX") return historiesByOutcome;
    const windowMs =
      range === "1H" ? 60 * 60 * 1000 : range === "24H" ? 24 * 60 * 60 * 1000 : 7 * 24 * 60 * 60 * 1000;
    const cutoff = maxTimestamp - windowMs;
    return historiesByOutcome.map((series) => {
      if (!series.length) return series;
      const sliced = series.filter((p) => p.x >= cutoff);
      return sliced.length >= 2 ? sliced : series;
    });
  }, [historiesByOutcome, maxTimestamp, range]);

  const dataSeries = useMemo(() => {
    const xSet = new Set<number>();
    filteredHistories.forEach((series) => {
      series.forEach((point) => xSet.add(point.x));
    });
    const xs = Array.from(xSet).sort((a, b) => a - b);
    const ys = filteredHistories.map((series) => {
      if (!series.length) return xs.map(() => null);
      const sorted = [...series].sort((a, b) => a.x - b.x);
      let idx = 0;
      let lastValue: number | null = null;
      return xs.map((x) => {
        while (idx < sorted.length && sorted[idx].x <= x) {
          if (sorted[idx].x === x) {
            lastValue = sorted[idx].y;
            idx += 1;
            return lastValue;
          }
          lastValue = sorted[idx].y;
          idx += 1;
        }
        return lastValue;
      });
    });
    return [xs, ...ys];
  }, [filteredHistories]);

  const alignedXs = dataSeries[0] as number[] | undefined;
  const selectedSeries =
    (dataSeries[selectedOutcome + 1] as Array<number | null> | undefined) ?? [];
  const selectedHistory = filteredHistories[selectedOutcome] ?? [];
  const activeIndex =
    hoverIndex !== null && alignedXs && alignedXs[hoverIndex] !== undefined
      ? hoverIndex
      : Math.max((alignedXs?.length ?? 0) - 1, 0);
  const activeX = alignedXs && alignedXs[activeIndex] !== undefined ? alignedXs[activeIndex] : null;
  const activeY =
    selectedSeries && selectedSeries[activeIndex] !== undefined ? selectedSeries[activeIndex] : null;
  const activePoint =
    activeX !== null && activeY !== null
      ? {
          x: activeX,
          y: activeY,
          timestamp: new Date(activeX).toISOString(),
          fx_stale: selectedHistory[activeIndex]?.fx_stale,
        }
      : null;
  const hoverActive = hoverIndex !== null && cursorPos !== null;
  const hoverValues = useMemo(() => {
    if (!alignedXs || activeX === null) return [];
    return outcomeOptions.map((label, idx) => {
      const series = dataSeries[idx + 1] as Array<number | null> | undefined;
      const value = series && series[activeIndex] !== undefined ? series[activeIndex] : null;
      const normalized = label.trim().toLowerCase();
      const color =
        normalized === "yes" || idx === 0 ? "#34d399" : normalized === "no" || idx === 1 ? "#fb7185" : "#94a3b8";
      return { label, value, color };
    });
  }, [activeIndex, activeX, alignedXs, dataSeries, outcomeOptions]);

  const tickSize =
    typeof streamState.tickSize === "number"
      ? streamState.tickSize
      : undefined;

  const chartRef = useRef<HTMLDivElement | null>(null);
  const plotRef = useRef<uPlot | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const plotKey = useMemo(() => outcomeOptions.join("|"), [outcomeOptions]);

  useEffect(() => {
    if (!chartRef.current) return;
    if ((alignedXs?.length ?? 0) < 2) {
      if (plotRef.current) {
        plotRef.current.destroy();
        plotRef.current = null;
      }
      setCursorPos(null);
      return;
    }

    const container = chartRef.current;
    const basePadding = { top: 12, right: 12, bottom: 12, left: 12 };

    const formatAxisTime = (value: number) =>
      formatTime(new Date(value), { hour: "2-digit", minute: "2-digit", second: undefined });
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

    const splinePath =
      (uPlot as any).paths?.spline ? (uPlot as any).paths.spline() : undefined;
    const linePath =
      (uPlot as any).paths?.linear ? (uPlot as any).paths.linear() : undefined;
    const pathFn = splinePath ?? linePath;
    const yesColor = "#34d399";
    const noColor = "#fb7185";
    const outcomeColors = outcomeOptions.map((label, idx) => {
      const normalized = label.trim().toLowerCase();
      if (normalized === "yes" || idx === 0) return yesColor;
      if (normalized === "no" || idx === 1) return noColor;
      return "#94a3b8";
    });
    const series = outcomeOptions.length
      ? outcomeOptions.map((label, idx) => {
          const isActive = idx === selectedOutcome;
          const color = outcomeColors[idx] ?? "#94a3b8";
          return {
            label,
            stroke: color,
            width: isActive ? 2.5 : 1.5,
            fill: "transparent",
            paths: pathFn,
            spanGaps: true,
            points: { show: false },
          };
        })
      : [
          {
            label: "Price",
            stroke: yesColor,
            width: 2,
            fill: "transparent",
            paths: pathFn,
            spanGaps: true,
            points: { show: false },
          },
        ];

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
        y: {
          range: [0, 1],
        },
      },
      axes: [
        {
          show: false,
          stroke: "rgba(148,163,184,0.6)",
          grid: { show: true, stroke: "rgba(148,163,184,0.18)", width: 1 },
          values: (_u, vals) => vals.map((v) => formatAxisTime(v)),
        },
        {
          show: false,
          stroke: "transparent",
          grid: { show: true, stroke: "rgba(148,163,184,0.14)", width: 1 },
          values: (_u, vals) => formatOutcomeLabels(vals),
        },
      ],
      series: [{}, ...series],
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
    const overlay = plotRef.current.over;
    if (overlay) {
      const existing = overlay.querySelector(".chart-outcome-labels");
      if (existing) {
        existing.remove();
      }
      const labels = document.createElement("div");
      labels.className =
        "chart-outcome-labels pointer-events-none absolute left-3 top-3 flex flex-col gap-1 text-[10px] uppercase tracking-[0.2em]";
      outcomeOptions.forEach((label, idx) => {
        const color = outcomeColors[idx] ?? "#94a3b8";
        const span = document.createElement("span");
        span.textContent = label;
        span.style.color = color;
        labels.appendChild(span);
      });
      overlay.appendChild(labels);
    }

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
  }, [alignedXs?.length, plotKey, outcomeOptions, dataSeries, selectedOutcome]);

  useEffect(() => {
    if (!plotRef.current) return;
    plotRef.current.setData(dataSeries as uPlot.AlignedData);
  }, [dataSeries]);

  return (
    <div className="rounded-2xl bg-transparent p-0">
      <div className="flex flex-col gap-3 text-sm text-slate-200">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-baseline gap-3">
            <span className="text-xs uppercase tracking-[0.2em] text-slate-500">Implied probability</span>
            <span className="text-2xl font-semibold text-white tabular-nums">
              {latestPrice !== null ? `${(latestPrice * 100).toFixed(2)}%` : "—"}
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
      </div>
      <div className="relative mt-4 h-72 rounded-2xl bg-gradient-to-b from-slate-900/90 via-slate-950/90 to-black/90 shadow-inner shadow-black/40 overflow-hidden">
        <MarketFomoOverlay marketId={marketId} tokenIds={tokenIds} outcomes={outcomes} />
        {filteredHistory.length >= 2 ? (
          <>
            <div ref={chartRef} className="market-chart absolute inset-0" />
            {activePoint && hoverActive && (
              <div
                className="pointer-events-none absolute rounded-lg border border-white/10 bg-slate-900/85 px-3 py-1 text-[11px] text-slate-100 shadow-lg"
                style={{
                  left: Math.max(10, Math.min((cursorPos?.x ?? 0) - 60, chartSize.width - 150)),
                  top: Math.max(8, Math.min((cursorPos?.y ?? 0) - 34, chartSize.height - 40)),
                }}
              >
                <div className="text-[11px] text-slate-200">{formatTime(activePoint.timestamp)}</div>
                <div className="mt-1 space-y-0.5">
                  {hoverValues.map((row) => (
                    <div key={row.label} className="flex items-center justify-between gap-3">
                      <span className="text-[10px] uppercase tracking-[0.2em]" style={{ color: row.color }}>
                        {row.label}
                      </span>
                      <span className="text-[11px] text-white">
                        {row.value !== null && row.value !== undefined ? `${(row.value * 100).toFixed(2)}%` : "—"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="flex h-full items-center justify-center text-slate-500">
            {error ? `No data: ${error}` : "Waiting for live prices..."}
          </div>
        )}
      </div>
    </div>
  );
}
