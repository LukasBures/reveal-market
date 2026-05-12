"use client";

import { useEffect, useRef } from "react";
import { useConnection } from "wagmi";
import { captureZenriseAttribution, recordZenriseWalletConnected } from "@/lib/zenriseJourney";

export function ZenriseJourneyTracker() {
  const { address, chain, connector, status } = useConnection();
  const lastWalletKeyRef = useRef<string | null>(null);

  useEffect(() => {
    captureZenriseAttribution();
  }, []);

  useEffect(() => {
    if (status !== "connected" || !address) {
      lastWalletKeyRef.current = null;
      return;
    }
    const walletKey = `${address.toLowerCase()}:${chain?.id ?? "unknown"}:${connector?.id ?? "unknown"}`;
    if (lastWalletKeyRef.current === walletKey) {
      return;
    }
    lastWalletKeyRef.current = walletKey;
    recordZenriseWalletConnected({
      address,
      chainId: chain?.id ?? null,
      connectorId: connector?.id ?? null,
      connectorName: connector?.name ?? null,
    });
  }, [address, chain?.id, connector?.id, connector?.name, status]);

  return null;
}
