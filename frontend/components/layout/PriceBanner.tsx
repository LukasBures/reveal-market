"use client";

type PriceBannerProps = {
  fxLabel: string | null;
  fxStale: boolean;
  fxError: string | null;
};

export function PriceBanner({ fxLabel, fxStale, fxError }: PriceBannerProps) {
  return (
    <div className="border-t border-white/5 bg-black/60 px-4 py-2 text-xs text-white/80">
      <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-end gap-2 md:gap-3">
        <div className="flex items-center gap-2 md:gap-3">
          {fxStale && <span className="text-amber-300 text-[11px] uppercase tracking-[0.2em]">FX stale</span>}
          {fxError && <span className="text-rose-300 text-[11px] uppercase tracking-[0.2em]">FX unavailable</span>}
          {!fxStale && !fxError && (
            <span className="text-emerald-300 text-[11px] uppercase tracking-[0.2em]">Live pricing</span>
          )}
        </div>
        <span className="rounded-full bg-white/5 px-2 py-1 text-[11px] font-semibold tracking-wide md:px-3">
          {fxLabel ? fxLabel : "ZEN/USDC loading ..."}
        </span>
      </div>
    </div>
  );
}
