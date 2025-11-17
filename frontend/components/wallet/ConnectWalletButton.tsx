"use client";

import { useMemo, useState } from "react";
import type { Connector } from "wagmi";
import {
  useAccount,
  useConnect,
  useDisconnect,
  useSignMessage,
  useSwitchChain,
} from "wagmi";

const CONNECTOR_ORDER = ["metaMask", "injected", "coinbaseWallet", "walletConnect"] as const;
const CONNECTOR_LABELS: Record<string, string> = {
  metaMask: "MetaMask",
  injected: "Injected",
  coinbaseWallet: "Coinbase Wallet",
  walletConnect: "WalletConnect",
};

function formatAddress(address?: string | null) {
  if (!address) {
    return "";
  }
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

function formatSignature(signature?: string | null) {
  if (!signature) {
    return null;
  }
  return `${signature.slice(0, 10)}…${signature.slice(-8)}`;
}

function getConnectorLabel(connector: Connector) {
  return CONNECTOR_LABELS[connector.id] ?? connector.name;
}

export function ConnectWalletButton() {
  const { address, chain, status: accountStatus } = useAccount();
  const {
    connect,
    connectors,
    status: connectStatus,
    error: connectError,
  } = useConnect();
  const { disconnect } = useDisconnect();
  const {
    data: signature,
    error: signError,
    isPending: isSigning,
    signMessageAsync,
  } = useSignMessage();
  const {
    chains,
    error: switchError,
    isPending: isSwitching,
    switchChain,
  } = useSwitchChain();

  const [message, setMessage] = useState("gm from Reveal Market");

  const orderedConnectors = useMemo(() => {
    const fallbackIndex = CONNECTOR_ORDER.length;
    const seen = new Set<string>();
    return connectors
      .filter((connector) => (connector.ready ?? true) && connector.id)
      .sort((a, b) => {
        const indexA = CONNECTOR_ORDER.indexOf(a.id as (typeof CONNECTOR_ORDER)[number]);
        const indexB = CONNECTOR_ORDER.indexOf(b.id as (typeof CONNECTOR_ORDER)[number]);
        return (indexA === -1 ? fallbackIndex : indexA) - (indexB === -1 ? fallbackIndex : indexB);
      })
      .filter((connector) => {
        if (seen.has(connector.id)) {
          return false;
        }
        seen.add(connector.id);
        return true;
      });
  }, [connectors]);

  const isConnected = accountStatus === "connected" && Boolean(address);
  const isConnecting = connectStatus === "pending";

  const handleConnect = (connector: Connector) => {
    connect({ connector });
  };

  const handleSignMessage = async () => {
    if (!message.trim()) {
      return;
    }
    try {
      await signMessageAsync({ message });
    } catch {
      // Handled by wagmi error state
    }
  };

  const handleSwitchChain = (chainId: number) => {
    if (!switchChain) {
      return;
    }
    try {
      switchChain({ chainId });
    } catch {
      // Error handled via switchError state
    }
  };

  return (
    <div className="w-full max-w-xs rounded-2xl border border-white/15 bg-white/5 p-4 text-xs text-white shadow-lg backdrop-blur">
      {isConnected ? (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2 rounded-xl border border-white/10 bg-black/40 p-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[11px] uppercase tracking-[0.25em] text-white/50">Connected</p>
                <p className="font-mono text-sm text-white">{formatAddress(address)}</p>
                <p className="text-[11px] text-white/60">{chain?.name ?? "Unknown network"}</p>
              </div>
              <button
                type="button"
                onClick={() => disconnect()}
                className="rounded-full border border-white/20 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.3em] text-white/80 transition hover:border-white hover:text-white"
              >
                Disconnect
              </button>
            </div>
          </div>

          <div className="flex flex-col gap-2 rounded-xl border border-white/10 bg-black/30 p-3">
            <p className="text-[11px] uppercase tracking-[0.25em] text-white/50">Sign message (optional)</p>
            <input
              type="text"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              className="rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-xs text-white placeholder:text-white/40 focus:border-white/40 focus:outline-none"
              placeholder="Enter a message"
            />
            <button
              type="button"
              onClick={handleSignMessage}
              disabled={isSigning || !message.trim()}
              className="rounded-lg bg-brand-500 px-3 py-2 text-center text-[11px] font-semibold uppercase tracking-[0.3em] text-white transition hover:bg-brand-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSigning ? "Signing…" : "Sign message"}
            </button>
            {signature ? (
              <p className="text-[11px] text-white/70">Signature: {formatSignature(signature)}</p>
            ) : null}
            {signError ? (
              <p className="text-[11px] text-rose-300">{signError.message}</p>
            ) : null}
          </div>

          <div className="flex flex-col gap-2 rounded-xl border border-white/10 bg-black/30 p-3">
            <p className="text-[11px] uppercase tracking-[0.25em] text-white/50">Switch network (optional)</p>
            <div className="flex flex-wrap gap-2">
              {chains.map((chainOption) => (
                <button
                  key={chainOption.id}
                  type="button"
                  onClick={() => handleSwitchChain(chainOption.id)}
                  disabled={!switchChain || isSwitching || chain?.id === chainOption.id}
                  className={
                    "rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.2em] transition " +
                    (chain?.id === chainOption.id
                      ? "border-brand-400 bg-brand-500/20 text-white"
                      : "border-white/15 text-white/80 hover:border-white hover:text-white")
                  }
                >
                  {chainOption.name}
                </button>
              ))}
            </div>
            {switchError ? (
              <p className="text-[11px] text-rose-300">{switchError.message}</p>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-[11px] uppercase tracking-[0.35em] text-white/60">Connect wallet</p>
          <div className="grid grid-cols-2 gap-2">
            {orderedConnectors.length ? (
              orderedConnectors.map((connector) => (
                <button
                  key={connector.id}
                  type="button"
                  disabled={isConnecting}
                  onClick={() => handleConnect(connector)}
                  className="rounded-xl border border-white/15 bg-black/30 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-white/80 transition hover:border-white hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {getConnectorLabel(connector)}
                </button>
              ))
            ) : (
              <p className="col-span-2 text-center text-[11px] text-white/60">Wallet connectors unavailable</p>
            )}
          </div>
          {connectError ? (
            <p className="text-[11px] text-rose-300">{connectError.message}</p>
          ) : null}
        </div>
      )}
    </div>
  );
}
