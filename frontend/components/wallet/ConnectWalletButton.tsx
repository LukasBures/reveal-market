"use client";

import { useEffect, useMemo, useState } from "react";
import { useAccount, useConnect, useDisconnect } from "wagmi";
import type { Connector } from "wagmi";

type DeviceState = {
  isClient: boolean;
  isMobile: boolean;
  hasMetaMask: boolean;
  hasCoinbaseWallet: boolean;
};

const INITIAL_DEVICE_STATE: DeviceState = {
  isClient: false,
  isMobile: false,
  hasMetaMask: false,
  hasCoinbaseWallet: false,
};

const connectorLabels: Record<string, { title: string; description: string }> = {
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
};

function detectDevice(): DeviceState {
  if (typeof window === "undefined") {
    return INITIAL_DEVICE_STATE;
  }

  const ua = window.navigator.userAgent || "";
  const hasEthereum = typeof (window as typeof window & { ethereum?: unknown }).ethereum !== "undefined";
  const ethereum = (window as typeof window & { ethereum?: { providers?: Array<Record<string, unknown>> } }).ethereum;
  const providers = ethereum?.providers ?? (ethereum ? [ethereum] : []);

  const providerHasFlag = (flag: string) => providers.some((provider) => Boolean((provider as never)?.[flag]));

  return {
    isClient: true,
    isMobile: /Android|iPhone|iPad|iPod/i.test(ua),
    hasMetaMask: providerHasFlag("isMetaMask"),
    hasCoinbaseWallet: providerHasFlag("isCoinbaseWallet"),
  };
}

function formatAddress(address?: string) {
  if (!address) {
    return "";
  }
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

function isConnectorAvailable(connector: Connector, device: DeviceState) {
  const connectorId = connector.id;

  if (connectorId === "metaMaskSDK") {
    return device.hasMetaMask;
  }

  if (connectorId === "coinbaseWalletSDK") {
    return device.hasCoinbaseWallet || !device.isMobile;
  }

  if (connectorId === "walletConnect") {
    return true;
  }

  return device.isClient;
}

export function ConnectWalletButton() {
  const { address, status } = useAccount();
  const { disconnect } = useDisconnect();
  const { connect, connectors, status: connectStatus, error, reset } = useConnect();
  const [device, setDevice] = useState<DeviceState>(INITIAL_DEVICE_STATE);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setDevice(detectDevice());
  }, []);

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

  const availableConnectors = useMemo(
    () => connectors.filter((connector) => isConnectorAvailable(connector, device)),
    [connectors, device],
  );

  async function copyAddress() {
    if (!address || typeof navigator?.clipboard === "undefined") {
      return;
    }
    await navigator.clipboard.writeText(address);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function handleConnect(connector: Connector) {
    connect({ connector });
  }

  const buttonLabel = address ? formatAddress(address) : "Connect Wallet";

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
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 py-8"
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
              {availableConnectors.length === 0 ? (
                <p className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
                  No compatible wallets detected in this browser. Try WalletConnect on mobile or install MetaMask or
                  Coinbase Wallet.
                </p>
              ) : (
                availableConnectors.map((connector) => {
                  const labels = connectorLabels[connector.id] ?? {
                    title: connector.name,
                    description: "Connect with this wallet",
                  };
                  const isConnecting = connectStatus === "pending";

                  return (
                    <button
                      key={connector.uid}
                      type="button"
                      onClick={() => handleConnect(connector)}
                      disabled={isConnecting}
                      className="w-full rounded-2xl border border-white/15 bg-white/5 px-4 py-3 text-left transition hover:border-white/40 hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-70"
                    >
                      <p className="text-base font-semibold">{labels.title}</p>
                      <p className="text-sm text-white/70">{labels.description}</p>
                    </button>
                  );
                })
              )}
            </div>

            {error ? <p className="mt-4 text-sm text-rose-400">{error.message}</p> : null}
          </div>
        </div>
      ) : null}
    </>
  );
}
