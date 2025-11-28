"use client";

import Image from "next/image";
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
import { defaultChain } from "@/lib/wagmi";

type ConnectorOption = {
  id: string;
  label: string;
  connectorId: Connector["id"];
  description: string;
  iconSrc: string;
  iconAlt: string;
};

type WagmiError = Error & { shortMessage?: string | undefined };

const formatErrorMessage = (error?: Error | null) => {
  if (!error) {
    return null;
  }
  const candidate =
    typeof (error as WagmiError).shortMessage === "string" && (error as WagmiError).shortMessage?.trim()
      ? (error as WagmiError).shortMessage
      : error.message;
  if (!candidate) {
    return null;
  }
  let sanitized = candidate
    .replace(/\s*\(version:[^)]+\)\s*$/i, "")
    .replace(/\bversion:\s*@?[\w./@-]+\b/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  const versionIndex = sanitized.toLowerCase().indexOf("version:");
  if (versionIndex !== -1) {
    sanitized = sanitized.slice(0, versionIndex).trim();
  }
  return sanitized || "Unable to connect. Please try again.";
};

const CONNECTOR_UI: ConnectorOption[] = [
  {
    id: "metamask",
    label: "MetaMask",
    connectorId: "metaMask",
    description: "Official extension",
    iconSrc: "/wallet-icons/metamask.svg",
    iconAlt: "MetaMask",
  },
  {
    id: "rabby",
    label: "Rabby",
    connectorId: "injected",
    description: "Rabby + injected",
    iconSrc: "/wallet-icons/rabby.svg",
    iconAlt: "Rabby",
  },
  {
    id: "coinbase",
    label: "Coinbase Wallet",
    connectorId: "coinbaseWalletSDK",
    description: "Browser & mobile",
    iconSrc: "/wallet-icons/coinbasewallet.svg",
    iconAlt: "Coinbase Wallet",
  },
  {
    id: "okx",
    label: "OKX Wallet",
    connectorId: "injected",
    description: "OKX, Bitget, Brave",
    iconSrc: "/wallet-icons/okx.svg",
    iconAlt: "OKX Wallet",
  },
  {
    id: "trust",
    label: "Trust Wallet",
    connectorId: "walletConnect",
    description: "WalletConnect (mobile)",
    iconSrc: "/wallet-icons/trust.svg",
    iconAlt: "Trust Wallet",
  },
  {
    id: "walletconnect",
    label: "WalletConnect",
    connectorId: "walletConnect",
    description: "QR code & all others",
    iconSrc: "/wallet-icons/walletconnect.svg",
    iconAlt: "WalletConnect",
  },
] as const;

type ConnectorMap = Record<string, Connector | undefined>;
const walletConnectEnabled =
  Boolean(process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID) || process.env.NODE_ENV === "test";

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
  const { address, chain, status: accountStatus, connector: activeConnector } = useAccount();
  const { connect, connectors, status: connectStatus, error: connectError } = useConnect();
  const { disconnect } = useDisconnect();
  const { data: signature, error: signError, isPending: isSigning, signMessageAsync } = useSignMessage();
  const {
    chains,
    error: switchError,
    isPending: isSwitching,
    switchChain,
    switchChainAsync,
  } = useSwitchChain();

  const [message, setMessage] = useState("gm from Reveal Market");
  const [isModalOpen, setModalOpen] = useState(false);
  const [selectedOption, setSelectedOption] = useState<ConnectorOption | null>(null);
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const modalTitleId = "wallet-modal-title";
  const [isMounted, setIsMounted] = useState(false);
  const [attemptedAutoSwitch, setAttemptedAutoSwitch] = useState(false);
  const [autoCloseOnConnect, setAutoCloseOnConnect] = useState(false);
  const isConnected = accountStatus === "connected" && Boolean(address);
  const activeConnectorId = activeConnector?.id;
  const connectErrorMessage = formatErrorMessage(connectError);
  const signErrorMessage = formatErrorMessage(signError);
  const switchErrorMessage = formatErrorMessage(switchError);

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
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isConnected) {
      setAttemptedAutoSwitch(false);
      return;
    }
    const switchFn = switchChainAsync ?? switchChain;
    if (chain?.id !== defaultChain.id && switchFn && !attemptedAutoSwitch) {
      setAttemptedAutoSwitch(true);
      Promise.resolve(switchFn({ chainId: defaultChain.id })).catch(() => setAttemptedAutoSwitch(false));
    }
  }, [attemptedAutoSwitch, chain?.id, isConnected, switchChain, switchChainAsync]);

  const connectorsById = useMemo<ConnectorMap>(() => {
    return connectors.reduce<ConnectorMap>((acc, connector) => {
      acc[connector.id] = connector;
      const connectorType = (connector as any).type;
      if (connectorType && !acc[connectorType]) {
        acc[connectorType] = connector;
      }
      return acc;
    }, {});
  }, [connectors]);

  const isMobileBrowser = useMemo(() => {
    if (!isMounted || typeof navigator === "undefined") {
      return false;
    }
    return /android|iphone|ipad|ipod|iemobile|blackberry|bb10/i.test(navigator.userAgent);
  }, [isMounted]);

  const providerFlags = useMemo(() => {
    if (!isMounted || typeof window === "undefined") {
      return { ethereum: null as any, providers: [] as any[] };
    }
    const ethereum = (window as any).ethereum;
    const providers = Array.isArray(ethereum?.providers)
      ? ethereum.providers.filter(Boolean)
      : ethereum
        ? [ethereum]
        : [];
    return { ethereum, providers };
  }, [isMounted]);

  const hasInjectedProvider = useCallback(
    (predicate: (provider: any) => boolean) => providerFlags.providers.some(predicate),
    [providerFlags.providers],
  );

  const availableOptions = useMemo(() => {
    return CONNECTOR_UI.filter((option) => {
      if (option.id === "walletconnect" && !walletConnectEnabled) {
        return false;
      }
      const connector = connectorsById[option.connectorId];
      if (!connector) return false;
      const ready = (connector as any).ready ?? true;
      if (!isMounted) return true;
      const ethereum = providerFlags.ethereum;
      const providersAvailable = providerFlags.providers.length > 0;

      // Determine if this connector is actually available in the current environment.
      let walletAvailable = false;
      if (!isMobileBrowser) {
        walletAvailable = true;
      } else if (option.connectorId === "walletConnect") {
        walletAvailable = true;
      } else if (option.connectorId === "metaMask") {
        walletAvailable =
          Boolean(ethereum?.isMetaMask) ||
          hasInjectedProvider((provider) => Boolean(provider?.isMetaMask));
      } else if (option.connectorId === "coinbaseWalletSDK") {
        walletAvailable =
          Boolean(ethereum?.isCoinbaseWallet) ||
          hasInjectedProvider((provider) => Boolean(provider?.isCoinbaseWallet));
      } else if (option.connectorId === "injected") {
        const hasNonMetaMask = hasInjectedProvider(
          (provider) => !provider?.isMetaMask && !provider?.isCoinbaseWallet,
        );
        walletAvailable = Boolean(
          (ethereum && !ethereum.isMetaMask && !ethereum.isCoinbaseWallet) || hasNonMetaMask,
        );
      }

      // If wagmi marks connector as not ready, allow it when we detected a matching provider.
      if (!ready && !walletAvailable) return false;

      // When no providers are present, hide injected wallets on mobile/desktop.
      if (!walletAvailable && !providersAvailable && !ethereum) return false;

      return walletAvailable;
    });
  }, [connectorsById, hasInjectedProvider, isMobileBrowser, isMounted, providerFlags]);

  useEffect(() => {
    if (!selectedOption) return;
    const stillAvailable = availableOptions.some((option) => option.id === selectedOption.id);
    if (!stillAvailable) {
      setSelectedOption(null);
      setAcceptedTerms(false);
    }
  }, [availableOptions, selectedOption]);

  const isConnecting = connectStatus === "pending";

  const handleConnect = (connector?: Connector) => {
    if (!connector) {
      console.warn("Connector unavailable for selected wallet option.");
      return;
    }
    setAutoCloseOnConnect(true);
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

  const handleSwitchChain = () => {
    if (!switchChain) {
      return;
    }
    switchChain({ chainId: defaultChain.id });
  };

  const closeModal = useCallback(() => {
    setModalOpen(false);
    setSelectedOption(null);
    setAcceptedTerms(false);
    setAutoCloseOnConnect(false);
  }, []);
  const openModal = () => {
    setModalOpen(true);
    setSelectedOption(null);
    setAcceptedTerms(false);
    setAutoCloseOnConnect(!isConnected);
  };

  useEffect(() => {
    if (isConnected && isModalOpen && autoCloseOnConnect) {
      closeModal();
    }
  }, [autoCloseOnConnect, closeModal, isConnected, isModalOpen]);

  useEffect(() => {
    if (connectStatus === "success" && isModalOpen && autoCloseOnConnect) {
      closeModal();
    }
    if (connectStatus === "error") {
      setAutoCloseOnConnect(false);
    }
  }, [autoCloseOnConnect, closeModal, connectStatus, isModalOpen]);

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
                {availableOptions.length === 0 ? (
                  <p className="rounded-xl border border-white/10 bg-white/5 px-3 py-4 text-center text-xs text-white/70">
                    No compatible wallets detected on this device. Try WalletConnect or switch devices.
                  </p>
                ) : (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {availableOptions.map((option) => {
                      const connector = connectorsById[option.connectorId];
                      const disabled = !connector || isConnecting;
                      const isSelected = selectedOption?.id === option.id;
                      const isActiveConnector = isConnected && activeConnectorId === connector?.id;
                      const stateClass = isActiveConnector
                        ? "border-emerald-400 bg-emerald-500/15 ring-1 ring-emerald-300/60"
                        : isSelected
                          ? "border-brand-400 bg-brand-500/20"
                          : "border-white/15 bg-white/5";
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
                          className={`group flex items-center gap-4 rounded-2xl border px-3 py-3 text-left text-sm font-semibold text-white/90 transition hover:border-white hover:text-white disabled:cursor-not-allowed disabled:opacity-50 ${stateClass}`}
                        >
                          <span className="flex h-16 w-16 flex-none items-center justify-center rounded-3xl bg-white/10 transition-transform duration-200 group-hover:scale-105">
                            <Image
                              src={option.iconSrc}
                              alt={option.iconAlt}
                              width={64}
                              height={64}
                              className="h-12 w-12 object-contain"
                            />
                          </span>
                          <span>
                            {option.label}
                            <span className="block text-xs font-normal text-white/60">{option.description}</span>
                            {isActiveConnector ? (
                              <span className="mt-1 inline-flex rounded-full bg-emerald-500/20 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.2em] text-emerald-200">
                                Connected
                              </span>
                            ) : null}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}
                {connectErrorMessage ? <p className="text-xs text-rose-300">{connectErrorMessage}</p> : null}
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
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={handleSwitchChain}
                            disabled={!switchChain || isSwitching || chain?.id === defaultChain.id}
                            className={
                              "rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.25em] transition " +
                              (chain?.id === defaultChain.id
                                ? "border-brand-400 bg-brand-500/20 text-white"
                                : "border-white/20 text-white/80 hover:border-white hover:text-white disabled:cursor-not-allowed disabled:opacity-50")
                            }
                          >
                            {chain?.id === defaultChain.id ? "On Horizen" : "Switch network"}
                          </button>
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
