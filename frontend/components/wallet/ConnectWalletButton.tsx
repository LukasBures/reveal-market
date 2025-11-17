"use client";

import { useEffect } from "react";
import { useAccount, useConnect, useDisconnect } from "wagmi";

function formatAddress(address?: string) {
  if (!address) {
    return "";
  }
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

export function ConnectWalletButton() {
  const { address, status } = useAccount();
  const { connect, connectors, status: connectStatus, error } = useConnect();
  const { disconnect } = useDisconnect();
  useEffect(() => {
    if (error) {
      console.error("Wallet connection failed:", error);
    }
  }, [error]);

  const primaryConnector = connectors[0];
  const isConnecting = connectStatus === "pending";
  const isConnected = status === "connected" && Boolean(address);

  if (isConnected && address) {
    return (
      <div className="flex items-center gap-3 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs font-semibold text-white/90 shadow-lg backdrop-blur">
        <span className="font-mono tracking-wider">{formatAddress(address)}</span>
        <button
          type="button"
          onClick={() => disconnect()}
          className="rounded-full border border-white/20 px-3 py-1 text-[11px] uppercase tracking-[0.25em] text-white/70 transition hover:border-white hover:text-white"
        >
          Disconnect
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-stretch gap-2">
      <button
        type="button"
        onClick={() => (primaryConnector ? connect({ connector: primaryConnector }) : undefined)}
        disabled={!primaryConnector || isConnecting}
        className="rounded-full bg-brand-500 px-4 py-2 text-center text-sm font-semibold text-white shadow-lg shadow-brand-500/40 transition hover:bg-brand-400 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isConnecting ? "Connecting…" : "Connect Wallet"}
      </button>
      {error ? <p className="text-center text-xs text-rose-300">Unable to connect. Please try again.</p> : null}
    </div>
  );
}
