"use client";

import { useCallback, useMemo } from "react";

type StakeInputProps = {
  outcomes: string[];
  outcomePrices: number[];
  selectedOutcome: number;
  stakeZen: number;
  ticketSize: number;
  tradingDisabled: boolean;
  onOutcomeSelect: (index: number) => void;
};

export function StakeInput({
  outcomes,
  outcomePrices,
  selectedOutcome,
  stakeZen: _stakeZen,
  ticketSize,
  tradingDisabled,
  onOutcomeSelect,
}: StakeInputProps) {
  const outcomeOptions = useMemo(() => (outcomes.length ? outcomes : ["Yes", "No"]), [outcomes]);
  const isBinary = outcomeOptions.length === 2;
  const normalizedPrices = useMemo(() => (Array.isArray(outcomePrices) ? outcomePrices : []), [outcomePrices]);

  const priceForOutcome = useCallback(
    (index: number): number | null => {
      const value = normalizedPrices[index];
      if (Number.isFinite(value)) return value;
      return null;
    },
    [normalizedPrices],
  );

  return (
    <>
      <div className="mt-4 space-y-3">
        {isBinary ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {[0, 1].map((idx) => {
              const label = outcomeOptions[idx] ?? (idx === 0 ? "Yes" : "No");
              const price = priceForOutcome(idx);
              const formattedPrice = price !== null ? `${Math.round(price * 100)}%` : "—";
              const active = selectedOutcome === idx;
              const isYes = idx === 0;
              return (
                <button
                  key={`${label}-${idx}`}
                  type="button"
                  onClick={() => onOutcomeSelect(idx)}
                  disabled={tradingDisabled}
                  className={`flex flex-col gap-1 rounded-2xl border px-4 py-3 text-left transition ${
                    active
                      ? isYes
                        ? "border-emerald-400 bg-emerald-500/15 text-white"
                        : "border-rose-400 bg-rose-500/15 text-white"
                      : "border-white/10 bg-white/5 text-white/80 hover:border-white/30 hover:bg-white/10"
                  } ${tradingDisabled ? "cursor-not-allowed opacity-60" : ""}`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-semibold uppercase tracking-[0.25em]">Buy {label}</span>
                    <span
                      className={`text-sm font-semibold ${
                        active ? (isYes ? "text-emerald-200" : "text-rose-200") : "text-emerald-200"
                      }`}
                    >
                      {formattedPrice}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            {outcomeOptions.map((label, idx) => (
              <button
                key={`${label}-${idx}`}
                type="button"
                onClick={() => onOutcomeSelect(idx)}
                disabled={tradingDisabled}
                className={`rounded-full px-3 py-2 text-xs font-semibold uppercase tracking-[0.2em] transition sm:py-1 ${
                  selectedOutcome === idx ? "bg-white text-slate-900" : "bg-white/10 text-white/80 hover:bg-white/20"
                } ${tradingDisabled ? "cursor-not-allowed opacity-60" : ""}`}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="mt-4 space-y-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-[0.2em] text-slate-500">Buy with ZEN</span>
          <input
            type="text"
            name="stakeZen"
            value={`${ticketSize.toFixed(2)} ZEN`}
            readOnly
            disabled
            className="w-full rounded-xl border border-white/15 bg-slate-900/80 px-3 py-2 text-white/70"
            aria-label="Fixed stake in ZEN"
          />
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">
            Fixed ticket size
          </p>
        </label>
      </div>
    </>
  );
}
