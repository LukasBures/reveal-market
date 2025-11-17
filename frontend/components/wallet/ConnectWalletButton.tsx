"use client";

import { useEffect, useMemo, useState } from "react";
import { useAccount, useConnect, useDisconnect } from "wagmi";
import type { Connector } from "wagmi";
import { primaryChain, walletConnectEnabled } from "@/lib/wallet/config";

const connectorLabels: Record<string, { title: string; description: string }> = {
  injected: {
    title: "Browser Wallet",
    description: "Connect with Brave, Rabby, or any injected provider",
  },
  metaMaskSDK: {
    title: "MetaMask",
    description: "Browser extension or MetaMask mobile browser",
  },
  walletConnect: {
    title: "WalletConnect",
    description: "Scan a QR code or deep link to 500+ wallets",
  },
  coinbaseWalletSDK: {
    title: "Coinbase Wallet",
    description: "Connect via the Coinbase Wallet extension or app",
  },
  coinbaseWallet: {
    title: "Coinbase Wallet",
    description: "Connect via the Coinbase Wallet extension or app",
  },
};

function formatAddress(address?: string) {
  if (!address) {
    return "";
  }
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

function sortConnectors(connectors: Connector[]) {
  const priority: Record<string, number> = {
    metaMaskSDK: 0,
    injected: 1,
    coinbaseWalletSDK: 2,
    coinbaseWallet: 2,
    walletConnect: 3,
  };
  return [...connectors].sort((a, b) => {
    const left = priority[a.id] ?? 99;
    const right = priority[b.id] ?? 99;
    return left - right;
  });
}

function connectorReady(connector: Connector) {
  if (connector.id === "walletConnect") {
    return true;
  }
  return Boolean((connector as Connector & { ready?: boolean }).ready);
}

export function ConnectWalletButton() {
  const { address, status, connector: activeConnector } = useAccount();
  const { disconnect } = useDisconnect();
  const {
    connectAsync,
    connectors,
    status: connectStatus,
    error,
    reset,
  } = useConnect();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [targetConnectorId, setTargetConnectorId] = useState<string | null>(null);

  useEffect(() => {
    if (!isModalOpen) {
      return;
    }

    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsModalOpen(false);
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isModalOpen]);

  useEffect(() => {
    if (status === "connected" && isModalOpen) {
      setIsModalOpen(false);
    }
  }, [status, isModalOpen]);

  useEffect(() => {
    if (!isModalOpen && connectStatus === "error") {
      reset();
    }
  }, [connectStatus, isModalOpen, reset]);

  const visibleConnectors = useMemo(() => {
    const list = [...connectors];
    return sortConnectors(list).filter((connector) => connectorReady(connector));
  }, [connectors]);

  async function copyAddress() {
    if (!address || typeof navigator?.clipboard === "undefined") {
      return;
    }
    await navigator.clipboard.writeText(address);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  async function handleConnect(connector: Connector) {
    setTargetConnectorId(connector.id);
    try {
      await connectAsync({
        connector,
        chainId: primaryChain?.id,
      });
    } finally {
      setTargetConnectorId(null);
    }
  }

  const buttonLabel = address ? formatAddress(address) : "Connect Wallet";
  const connectedLabel = activeConnector?.name ? `Connected via ${activeConnector.name}` : null;
  const isConnecting = connectStatus === "pending";
  const pendingConnectorId = targetConnectorId;

  return (
    <>
      <button
        type="button"
        onClick={() => setIsModalOpen(true)}
        className="rounded-full bg-brand-500 px-4 py-2 text-center text-sm font-semibold text-white shadow-lg shadow-brand-500/40 transition hover:bg-brand-400 sm:px-4 sm:py-1"
      >
        {buttonLabel}
      </button>

      {isModalOpen ? (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div
            className="flex min-h-full items-center justify-center bg-gradient-to-b from-black/85 via-black/80 to-black/85 px-4 py-16 sm:py-20"
            onClick={() => setIsModalOpen(false)}
          >
            <div
              role="dialog"
              aria-modal="true"
              className="w-full max-w-md rounded-2xl border border-white/10 bg-slate-950/95 p-6 text-white shadow-2xl"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-white/60">Wallet access</p>
                  <h2 className="text-2xl font-semibold">Connect your wallet</h2>
                </div>
              <button
                type="button"
                aria-label="Close wallet modal"
                onClick={() => setIsModalOpen(false)}
                className="rounded-full border border-white/20 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-white/80 transition hover:bg-white/10"
              >
                Close
              </button>
            </div>

            {address ? (
              <div className="mt-6 rounded-xl border border-white/10 bg-white/5 p-4">
                <p className="text-sm text-white/70">Connected wallet</p>
                <p className="mt-1 text-lg font-semibold">{formatAddress(address)}</p>
                {connectedLabel ? <p className="text-xs uppercase tracking-[0.3em] text-white/60">{connectedLabel}</p> : null}
                <div className="mt-4 flex gap-3">
                  <button
                    type="button"
                    onClick={copyAddress}
                    className="flex-1 rounded-full border border-white/20 px-4 py-2 text-sm font-semibold text-white transition hover:bg-white/10"
                  >
                    {copied ? "Copied" : "Copy address"}
                  </button>
                  <button
                    type="button"
                    onClick={() => disconnect()}
                    className="flex-1 rounded-full border border-white/20 px-4 py-2 text-sm font-semibold text-white transition hover:bg-white/10"
                  >
                    Disconnect
                  </button>
                </div>
              </div>
            ) : null}

            <div className="mt-6 space-y-3">
              {visibleConnectors.length === 0 ? (
                <p className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
                  No compatible wallets detected in this browser. {walletConnectEnabled ? "Try WalletConnect on mobile or install MetaMask or Coinbase Wallet." : "Set NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID to enable QR / mobile connections."}
                </p>
              ) : (
                visibleConnectors.map((connector) => {
                  const labels = connectorLabels[connector.id] ?? {
                    title: connector.name,
                    description: "Connect with this wallet",
                  };
                  const isTargeted = isConnecting && pendingConnectorId === connector.id;

                  return (
                    <button
                      key={connector.uid}
                      type="button"
                      onClick={() => handleConnect(connector)}
                      disabled={connectStatus === "pending"}
                      className="w-full rounded-2xl border border-white/15 bg-white/5 px-4 py-3 text-left transition hover:border-white/40 hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-70"
                      aria-busy={isTargeted}
                    >
                      <p className="text-base font-semibold">{labels.title}</p>
                      <p className="text-sm text-white/70">
                        {isTargeted ? "Awaiting approval..." : labels.description}
                      </p>
                    </button>
                  );
                })
              )}
            </div>
              {error ? <p className="mt-4 text-sm text-rose-400">{error.message}</p> : null}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
