"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import type { Connector } from "wagmi";
import {
  useAccount,
  useConnect,
  useDisconnect,
  useSignMessage,
  useSwitchChain,
} from "wagmi";

type ConnectorOption = {
  id: string;
  label: string;
  connectorId: Connector["id"];
  description: string;
  icon: string;
};

const CONNECTOR_UI: ConnectorOption[] = [
  {
    id: "metamask",
    label: "MetaMask",
    connectorId: "metaMask",
    description: "Official extension",
    icon: "metamask",
  },
  {
    id: "rabby",
    label: "Rabby",
    connectorId: "injected",
    description: "Rabby + injected",
    icon: "rabby",
  },
  {
    id: "coinbase",
    label: "Coinbase Wallet",
    connectorId: "coinbaseWallet",
    description: "Browser & mobile",
    icon: "coinbase",
  },
  {
    id: "okx",
    label: "OKX Wallet",
    connectorId: "injected",
    description: "OKX, Bitget, Brave",
    icon: "okx",
  },
  {
    id: "trust",
    label: "Trust Wallet",
    connectorId: "walletConnect",
    description: "WalletConnect (mobile)",
    icon: "trust",
  },
  {
    id: "walletconnect",
    label: "WalletConnect",
    connectorId: "walletConnect",
    description: "QR code & all others",
    icon: "walletConnect",
  },
] as const;

type ConnectorMap = Record<string, Connector | undefined>;

function ConnectorIcon({ id }: { id: string }) {
  switch (id) {
    case "metaMask":
      return (
        <svg viewBox="0 0 32 32" className="h-4 w-4" aria-hidden="true">
          <path d="M16 2L6 12l10 6 10-6z" fill="#f6851b" />
          <path d="M6 12l4 16 6-6 6 6 4-16-10 6z" fill="#ed8e24" />
        </svg>
      );
    case "coinbaseWallet":
      return (
        <svg viewBox="0 0 32 32" className="h-4 w-4" aria-hidden="true">
          <rect width="32" height="32" rx="16" fill="#0052ff" />
          <rect x="10" y="10" width="12" height="12" rx="6" fill="white" />
        </svg>
      );
    case "rabby":
      return (
        <svg viewBox="0 0 32 32" className="h-4 w-4" aria-hidden="true">
          <rect width="32" height="32" rx="16" fill="#ff5c82" />
          <path d="M10 18c3-1 9-1 12 0l-2 6H12z" fill="white" />
        </svg>
      );
    case "okx":
      return (
        <svg viewBox="0 0 32 32" className="h-4 w-4" aria-hidden="true">
          <rect width="32" height="32" rx="6" fill="black" />
          <path d="M7 10h5v12H7zM20 10h5v12h-5zM13 14h6v4h-6z" fill="white" />
        </svg>
      );
    case "trust":
      return (
        <svg viewBox="0 0 32 32" className="h-4 w-4" aria-hidden="true">
          <path d="M16 4l8 3v8c0 5.5-3.5 10.5-8 13-4.5-2.5-8-7.5-8-13V7z" fill="#2a72de" />
          <path d="M16 6.2l6 2.2v6.6c0 4.3-2.4 8.3-6 10.7-3.6-2.4-6-6.4-6-10.7V8.4z" fill="white" />
        </svg>
      );
    case "walletConnect":
      return (
        <svg viewBox="0 0 32 32" className="h-4 w-4" aria-hidden="true">
          <path
            d="M8 13.5c2.7-2.8 7.1-2.8 9.8 0l.2.2.2-.2c2.7-2.8 7.1-2.8 9.8 0l4.2 4.4-3 3-4.2-4.3c-1.2-1.3-3.2-1.3-4.4 0l-.2.2-.2-.2c-1.2-1.3-3.2-1.3-4.4 0L11 21l-3-3z"
            fill="#4196fc"
          />
        </svg>
      );
    default:
      return (
        <svg viewBox="0 0 32 32" className="h-4 w-4" aria-hidden="true">
          <circle cx="16" cy="16" r="14" fill="#7c84ff" />
        </svg>
      );
  }
}

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

export function ConnectWalletButton() {
  const { address, chain, status: accountStatus } = useAccount();
  const { connect, connectors, status: connectStatus, error: connectError } = useConnect();
  const { disconnect } = useDisconnect();
  const { data: signature, error: signError, isPending: isSigning, signMessageAsync } = useSignMessage();
  const {
    chains,
    error: switchError,
    isPending: isSwitching,
    switchChain,
  } = useSwitchChain();

  const [message, setMessage] = useState("gm from Reveal Market");
  const [isModalOpen, setModalOpen] = useState(false);
  const [selectedOption, setSelectedOption] = useState<ConnectorOption | null>(null);
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const modalTitleId = "wallet-modal-title";
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    if (!isModalOpen) {
      return;
    }
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setModalOpen(false);
      }
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [isModalOpen]);

  useEffect(() => {
    if (connectError) {
      console.error("Wallet connect error:", connectError);
    }
  }, [connectError]);

  useEffect(() => {
    if (signError) {
      console.error("Sign message error:", signError);
    }
  }, [signError]);

  useEffect(() => {
    if (switchError) {
      console.error("Switch chain error:", switchError);
    }
  }, [switchError]);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  const connectorsById = useMemo<ConnectorMap>(() => {
    return connectors.reduce<ConnectorMap>((acc, connector) => {
      acc[connector.id] = connector;
      return acc;
    }, {});
  }, [connectors]);

  const isConnected = accountStatus === "connected" && Boolean(address);
  const isConnecting = connectStatus === "pending";

  const handleConnect = (connector?: Connector) => {
    if (!connector) {
      console.warn("Connector unavailable for selected wallet option.");
      return;
    }
    connect({ connector });
  };

  const handleSignMessage = async () => {
    if (!message.trim()) {
      return;
    }
    try {
      await signMessageAsync({ message });
    } catch {
      // handled by wagmi state
    }
  };

  const handleSwitchChain = (chainId: number) => {
    if (!switchChain) {
      return;
    }
    switchChain({ chainId });
  };

  const closeModal = useCallback(() => {
    setModalOpen(false);
    setSelectedOption(null);
    setAcceptedTerms(false);
  }, []);
  const openModal = () => {
    setModalOpen(true);
    setSelectedOption(null);
    setAcceptedTerms(false);
  };

  const buttonLabel = (() => {
    if (isConnecting) {
      return "Connecting…";
    }
    if (isConnected && address) {
      return formatAddress(address);
    }
    return "Connect Wallet";
  })();

  const walletModal =
    isMounted && isModalOpen
      ? createPortal(
          (
            <div className="fixed inset-0 z-50 flex min-h-screen items-center justify-center overflow-y-auto p-4">
              <div
                className="absolute inset-0 bg-black/75 backdrop-blur-sm"
                onClick={closeModal}
                aria-hidden="true"
              />
              <div
                role="dialog"
                aria-modal="true"
                aria-labelledby={modalTitleId}
                className="relative z-10 w-full max-w-xl rounded-3xl border border-white/15 bg-gradient-to-b from-slate-950/95 via-slate-950/90 to-slate-900/90 p-6 text-white shadow-[0_40px_160px_rgba(8,15,40,0.85)]"
                onClick={(event) => event.stopPropagation()}
              >
            <div className="flex items-start justify-between gap-4 border-b border-white/10 pb-4">
              <div>
                <p id={modalTitleId} className="text-lg font-semibold text-white">
                  Connect wallet
                </p>
                <p className="text-xs text-white/60">
                  {isConnected && address ? "Manage your session" : "Choose a wallet to continue"}
                </p>
              </div>
              <button
                type="button"
                onClick={closeModal}
                className="rounded-md border border-white/30 bg-white/5 p-2 text-white/70 shadow-inner transition hover:border-white hover:text-white"
                aria-label="Close wallet dialog"
              >
                <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" className="h-3.5 w-3.5">
                  <path d="M5 5l10 10m0-10L5 15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </button>
            </div>

            <div className="mt-5 space-y-4">
              <div className="space-y-3">
                <p className="text-[11px] uppercase tracking-[0.35em] text-white/50">Wallet providers</p>
                {connectors.length === 0 ? (
                  <p className="rounded-xl border border-white/10 bg-white/5 px-3 py-4 text-center text-xs text-white/70">
                    Wallet connectors are initializing. Please wait…
                  </p>
                ) : (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {CONNECTOR_UI.map((option) => {
                      const connector = connectorsById[option.connectorId];
                      const disabled = !connector || isConnecting;
                      const isSelected = selectedOption?.id === option.id;
                      return (
                        <button
                          key={option.id}
                          type="button"
                          disabled={disabled}
                          onClick={() => {
                            if (disabled) {
                              return;
                            }
                            setSelectedOption(option);
                            setAcceptedTerms(false);
                          }}
                          className={`flex items-center gap-3 rounded-2xl border px-3 py-3 text-left text-sm font-semibold text-white/90 transition hover:border-white hover:text-white disabled:cursor-not-allowed disabled:opacity-50 ${
                            isSelected ? "border-brand-400 bg-brand-500/20" : "border-white/15 bg-white/5"
                          }`}
                        >
                          <span className="flex h-16 w-16 flex-none items-center justify-center rounded-3xl bg-white/10">
                            <ConnectorIcon id={option.icon} />
                          </span>
                          <span>
                            {option.label}
                            <span className="block text-xs font-normal text-white/60">{option.description}</span>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}
                {connectError ? (
                  <p className="text-xs text-rose-300">
                    {connectError.message || "Unable to connect. Please try again."}
                  </p>
                ) : null}
              </div>
              {selectedOption ? (
                <div className="space-y-4 rounded-2xl border border-white/10 bg-black/30 p-4">
                  <div>
                    <p className="text-base font-semibold text-white">Connect wallet</p>
                    <p className="text-xs uppercase tracking-[0.3em] text-white/50">Terms and Conditions agreement</p>
                  </div>
                  <p className="text-sm text-white/70">
                    By connecting your wallet, you acknowledge that you have read and agree to the{" "}
                    <Link
                      href="/terms"
                      className="text-brand-300 underline underline-offset-4"
                      target="_blank"
                      rel="noreferrer"
                      onClick={closeModal}
                    >
                      Terms of Service
                    </Link>{" "}
                    and{" "}
                    <Link
                      href="/privacy"
                      className="text-brand-300 underline underline-offset-4"
                      target="_blank"
                      rel="noreferrer"
                      onClick={closeModal}
                    >
                      Privacy Policy
                    </Link>
                    , and that you understand the protocol documentation and associated risks.
                  </p>
                  <label className="flex items-start gap-3 text-sm text-white/80">
                    <input
                      type="checkbox"
                      className="mt-1 h-4 w-4 rounded border-white/30 bg-transparent text-brand-400 focus:ring-brand-400"
                      checked={acceptedTerms}
                      onChange={(event) => setAcceptedTerms(event.target.checked)}
                    />
                    <span>
                      I have read the{" "}
                      <Link
                        href="/terms"
                        className="text-brand-300 underline underline-offset-4"
                        target="_blank"
                        rel="noreferrer"
                        onClick={closeModal}
                      >
                        Terms and Conditions
                      </Link>{" "}
                      and I accept them.
                    </span>
                  </label>
                  <button
                    type="button"
                    disabled={isConnecting || !acceptedTerms}
                    onClick={() => handleConnect(connectorsById[selectedOption.connectorId])}
                    className="w-full rounded-2xl bg-brand-500 px-4 py-2.5 text-center text-sm font-semibold text-white transition hover:bg-brand-400 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isConnecting ? "Connecting…" : `Connect with ${selectedOption.label}`}
                  </button>
                </div>
              ) : null}

              {isConnected ? (
                <>
                  <div className="rounded-2xl border border-white/10 bg-black/30 p-4">
                    <div className="flex flex-col gap-2">
                      <p className="text-[11px] uppercase tracking-[0.25em] text-white/50">Connected</p>
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="font-mono text-sm">{formatAddress(address)}</p>
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
                  </div>

                  <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                    <p className="text-[11px] uppercase tracking-[0.25em] text-white/50">Sign message (optional)</p>
                    <div className="mt-2 flex flex-col gap-2">
                      <input
                        type="text"
                        value={message}
                        onChange={(event) => setMessage(event.target.value)}
                        placeholder="Enter a message"
                        className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-xs text-white placeholder:text-white/40 focus:border-white/40 focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={handleSignMessage}
                        disabled={isSigning || !message.trim()}
                        className="rounded-xl bg-brand-500 px-3 py-2 text-center text-[11px] font-semibold uppercase tracking-[0.3em] text-white transition hover:bg-brand-400 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {isSigning ? "Signing…" : "Sign message"}
                      </button>
                      {signature ? (
                        <p className="text-[11px] text-white/70">Signature: {formatSignature(signature)}</p>
                      ) : null}
                      {signError ? <p className="text-[11px] text-rose-300">{signError.message}</p> : null}
                    </div>
                  </div>

                  <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                    <p className="text-[11px] uppercase tracking-[0.25em] text-white/50">Switch network (optional)</p>
                    <div className="mt-2 flex flex-wrap gap-2">
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
                              : "border-white/15 text-white/80 hover:border-white hover:text-white disabled:cursor-not-allowed disabled:opacity-50")
                          }
                        >
                          {chainOption.name}
                        </button>
                      ))}
                    </div>
                    {switchError ? <p className="text-[11px] text-rose-300">{switchError.message}</p> : null}
                  </div>
                </>
              ) : null}
            </div>
          </div>
        </div>
          ),
          document.body
        )
      : null;

  return (
    <div>
      <button
        type="button"
        onClick={openModal}
        className="inline-flex items-center gap-3 rounded-full bg-brand-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-brand-500/40 transition hover:bg-brand-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-300"
      >
        {buttonLabel}
        {isConnected && chain ? (
          <span className="rounded-full bg-white/20 px-2 py-0.5 text-[11px] uppercase tracking-[0.3em] text-white/80">
            {chain.name}
          </span>
        ) : null}
      </button>
      {walletModal}
    </div>
  );
}
