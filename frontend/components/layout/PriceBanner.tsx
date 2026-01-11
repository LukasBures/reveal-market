"use client";

import { useMemo } from "react";
import { useConnection, useSwitchChain } from "wagmi";
import { defaultChain } from "@/lib/wagmi";

type PriceBannerProps = {
  fxLabel: string | null;
  fxStale: boolean;
  fxError: string | null;
  apiWarning?: string | null;
  streamerWarning?: string | null;
};

export function PriceBanner({
  fxLabel,
  fxStale,
  fxError,
  apiWarning = null,
  streamerWarning = null,
}: PriceBannerProps) {
  const { chain, status: accountStatus, connector } = useConnection();
  const { mutate: switchChainMutate, isPending: isSwitching } = useSwitchChain();
  const switchChainSupported = typeof connector?.switchChain === "function";
  const switchChain = switchChainSupported ? switchChainMutate : undefined;
  const wrongNetwork = useMemo(() => {
    if (accountStatus !== "connected") return false;
    if (!chain?.id) return false;
    return chain.id !== defaultChain.id;
  }, [accountStatus, chain]);
  const showLive = !fxStale && !fxError && !apiWarning && !streamerWarning;

  const handleSwitch = () => {
    if (!switchChain) return;
    switchChain({ chainId: defaultChain.id });
  };

  return (
    <div className="border-t border-white/5 bg-black/60 text-xs text-white/80">
      <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-end gap-2 px-4 py-2 md:gap-3">
        <div className="flex flex-wrap items-center gap-2 md:gap-3">
          {wrongNetwork ? (
            <>
              <span className="text-amber-300 text-[11px] uppercase tracking-[0.2em]">Wrong network</span>
              <button
                type="button"
                onClick={handleSwitch}
                disabled={!switchChain || isSwitching}
                className="rounded-full bg-white/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-white transition hover:bg-white/20 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSwitching ? "Switching…" : `Switch to ${defaultChain.name}`}
              </button>
            </>
          ) : (
            <>
              {apiWarning && (
                <span className="text-rose-300 text-[11px] uppercase tracking-[0.2em]">{apiWarning}</span>
              )}
              {streamerWarning && (
                <span className="text-amber-300 text-[11px] uppercase tracking-[0.2em]">{streamerWarning}</span>
              )}
              {fxStale && <span className="text-amber-300 text-[11px] uppercase tracking-[0.2em]">FX stale</span>}
              {fxError && <span className="text-rose-300 text-[11px] uppercase tracking-[0.2em]">FX unavailable</span>}
              {showLive && (
                <span className="text-emerald-300 text-[11px] uppercase tracking-[0.2em]">Live pricing</span>
              )}
            </>
          )}
        </div>
        <span className="rounded-full bg-white/5 px-2 py-1 text-[11px] font-semibold tracking-wide md:px-3">
          {fxLabel ? fxLabel : "ZEN/USD loading ..."}
        </span>
      </div>
    </div>
  );
}
