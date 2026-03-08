"use client";

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import type { Connector } from "wagmi";
import { useConnect, useConnectors, useConnection, useDisconnect, useSwitchChain } from "wagmi";
import { ensureEip6963Discovery, getEip6963Providers, type Eip6963ProviderDetail } from "@/lib/eip6963";
import { defaultChain } from "@/lib/wagmi";
import { CopyButton } from "@/components/ui/CopyButton";

type ConnectorOption = {
  id: string;
  label: string;
  connectorId: Connector["id"];
  description: string;
  iconSrc: string;
  iconAlt: string;
  rdns?: string;
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
    rdns: "io.metamask",
  },
  {
    id: "rabby",
    label: "Rabby",
    connectorId: "rabby",
    description: "Rabby + injected",
    iconSrc: "/wallet-icons/rabby.svg",
    iconAlt: "Rabby",
    rdns: "io.rabby",
  },
  {
    id: "coinbase",
    label: "Coinbase Wallet",
    connectorId: "coinbaseWalletSDK",
    description: "Browser & mobile",
    iconSrc: "/wallet-icons/coinbasewallet.svg",
    iconAlt: "Coinbase Wallet",
    rdns: "com.coinbase.wallet",
  },
  {
    id: "okx",
    label: "OKX Wallet",
    connectorId: "okx",
    description: "OKX, Bitget, Brave",
    iconSrc: "/wallet-icons/okx.svg",
    iconAlt: "OKX Wallet",
    rdns: "com.okx.wallet",
  },
  {
    id: "trust",
    label: "Trust Wallet",
    connectorId: "walletConnect",
    description: "WalletConnect (mobile)",
    iconSrc: "/wallet-icons/trust.svg",
    iconAlt: "Trust Wallet",
    rdns: "com.trustwallet",
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
const RDNS_ALIASES: Record<string, string[]> = {
  okx: ["com.okx.wallet", "com.okex.wallet"],
  trust: ["com.trustwallet"],
  coinbase: ["com.coinbase.wallet"],
  metamask: ["io.metamask"],
  rabby: ["io.rabby"],
};
const walletConnectEnabled =
  Boolean(process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID) || process.env.NODE_ENV === "test";

function formatAddress(address?: string | null) {
  if (!address) {
    return "";
  }
  return `${address.slice(0, 6)}...${address.slice(-4)}`;
}

export function ConnectWalletButton() {
  const { address, chain, status: accountStatus, connector: activeConnector } = useConnection();
  const { mutate: connect, status: connectStatus, error: connectError } = useConnect();
  const connectors = useConnectors();
  const { mutate: disconnect } = useDisconnect();
  const {
    error: switchError,
    isPending: isSwitching,
    mutate: switchChainMutate,
    mutateAsync: switchChainMutateAsync,
  } = useSwitchChain();
  const switchChainSupported = typeof activeConnector?.switchChain === "function";
  const switchChain = switchChainSupported ? switchChainMutate : undefined;
  const switchChainAsync = switchChainSupported ? switchChainMutateAsync : undefined;

  const [isModalOpen, setModalOpen] = useState(false);
  const [selectedOption, setSelectedOption] = useState<ConnectorOption | null>(null);
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const modalTitleId = "wallet-modal-title";
  const [isMounted, setIsMounted] = useState(false);
  const [attemptedAutoSwitch, setAttemptedAutoSwitch] = useState(false);
  const [switchFailure, setSwitchFailure] = useState<string | null>(null);
  const [autoCloseOnConnect, setAutoCloseOnConnect] = useState(false);
  const isConnected = accountStatus === "connected" && Boolean(address);
  const activeConnectorId = activeConnector?.id;
  const connectErrorMessage = formatErrorMessage(connectError);
  const chainMismatch = isConnected && chain?.id !== defaultChain.id;
  const [lastConnectedAddress, setLastConnectedAddress] = useState<string | null>(() => {
    try {
      return localStorage.getItem("rm_last_wallet_address");
    } catch {
      return null;
    }
  });
  const [lastConnectedChainName, setLastConnectedChainName] = useState<string | null>(null);
  const [eip6963Providers, setEip6963Providers] = useState<Record<string, Eip6963ProviderDetail>>({});

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
    if (!isMounted || typeof window === "undefined") {
      return;
    }
    ensureEip6963Discovery();
    const syncProviders = () => {
      setEip6963Providers(getEip6963Providers());
    };
    syncProviders();
    const handleProvider = (event: Event) => {
      const detail = (event as CustomEvent<Eip6963ProviderDetail>).detail;
      if (!detail?.info?.rdns) {
        return;
      }
      syncProviders();
    };
    window.addEventListener("eip6963:announceProvider", handleProvider as EventListener);
    return () => {
      window.removeEventListener("eip6963:announceProvider", handleProvider as EventListener);
    };
  }, [isMounted]);

  useEffect(() => {
    if (!isConnected || !chain) {
      setAttemptedAutoSwitch(false);
      setSwitchFailure(null);
      return;
    }
    const switchFn = switchChainAsync ?? switchChain;
    if (chain.id === defaultChain.id) {
      setAttemptedAutoSwitch(false);
      setSwitchFailure(null);
      return;
    }
    if (!switchFn) {
      setSwitchFailure(`Switch to ${defaultChain.name} in your wallet to trade.`);
      return;
    }
    if (!attemptedAutoSwitch) {
      setAttemptedAutoSwitch(true);
      Promise.resolve(switchFn({ chainId: defaultChain.id }))
        .then(() => setSwitchFailure(null))
        .catch((error: unknown) => {
          setSwitchFailure(
            formatErrorMessage(error instanceof Error ? error : switchError) ??
              `Switch to ${defaultChain.name} to trade.`,
          );
        });
    }
  }, [attemptedAutoSwitch, chain, isConnected, switchChain, switchChainAsync, switchError]);

  useEffect(() => {
    if (isConnected && address) {
      setLastConnectedAddress(address);
      try { localStorage.setItem("rm_last_wallet_address", address); } catch { /* quota */ }
    }
    if (isConnected && chain?.name) {
      setLastConnectedChainName(chain.name);
    }
    if (accountStatus === "disconnected") {
      setLastConnectedAddress(null);
      setLastConnectedChainName(null);
      try { localStorage.removeItem("rm_last_wallet_address"); } catch { /* noop */ }
    }
  }, [accountStatus, address, chain?.name, isConnected]);

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }
    // UI hint only. Server-side route access control must not rely on this cookie.
    const maxAge = isConnected ? 60 * 60 * 24 * 7 : 0;
    const parts = [`wallet_session=${isConnected ? "1" : ""}`, "Path=/", `Max-Age=${maxAge}`, "SameSite=Lax"];
    if (window.location.protocol === "https:") {
      parts.push("Secure");
    }
    document.cookie = parts.join("; ");
  }, [isConnected]);

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

  const hasEip6963Providers = Object.keys(eip6963Providers).length > 0;

  const resolveEipProvider = useCallback(
    (option: ConnectorOption) => {
      if (!option.rdns) {
        return null;
      }
      const direct = eip6963Providers[option.rdns];
      if (direct) {
        return direct;
      }
      if (option.id === "okx") {
        return RDNS_ALIASES.okx.map((alias) => eip6963Providers[alias]).find(Boolean) ?? null;
      }
      return null;
    },
    [eip6963Providers],
  );

  const connectorOptions = useMemo(() => {
    return CONNECTOR_UI.map((option) => {
      const connector = connectorsById[option.connectorId];
      const ready = Boolean((connector as any)?.ready ?? true);
      const eipProvider = resolveEipProvider(option);

      if (!isMounted) {
        const available =
          option.connectorId === "walletConnect" ? walletConnectEnabled && Boolean(connector) : ready && Boolean(connector);
        return { option, connector, available, eipProvider, reason: null as string | null };
      }

      const hasProviderMatch = (predicate: (provider: any) => boolean) =>
        providerFlags.providers.some(predicate);
      const hasMetaMask = hasProviderMatch((provider) => Boolean(provider?.isMetaMask));
      const hasCoinbaseWallet = hasProviderMatch((provider) => Boolean(provider?.isCoinbaseWallet));
      const hasRabbyWallet = hasProviderMatch((provider) => Boolean(provider?.isRabby));
      const hasOkxWallet = hasProviderMatch((provider) => Boolean(provider?.isOkxWallet || provider?.isOKExWallet));
      const hasTrustWallet = hasProviderMatch((provider) => Boolean(provider?.isTrust || provider?.isTrustWallet));
      const hasOtherInjected = hasProviderMatch(
        (provider) => Boolean(provider) && !provider?.isMetaMask && !provider?.isCoinbaseWallet,
      );
      const detectedMetaMask = hasMetaMask || Boolean(eipProvider);
      const detectedCoinbase = hasCoinbaseWallet || Boolean(eipProvider);
      const detectedRabby = hasRabbyWallet || Boolean(eipProvider);
      const detectedOkx = hasOkxWallet || Boolean(eipProvider);
      const detectedTrust = hasTrustWallet || Boolean(eipProvider);

      let available: boolean;
      if (option.rdns && hasEip6963Providers) {
        available = Boolean(eipProvider) && Boolean(connector);
      } else if (option.connectorId === "walletConnect") {
        available = walletConnectEnabled && Boolean(connector);
      } else if (option.connectorId === "metaMask") {
        available = Boolean(connector) && ready && (hasMetaMask || Boolean(eipProvider));
      } else if (option.connectorId === "coinbaseWalletSDK") {
        available = Boolean(connector) && ready && (hasCoinbaseWallet || Boolean(eipProvider));
      } else if (option.connectorId === "rabby") {
        available = Boolean(connector) && ready && (hasRabbyWallet || Boolean(eipProvider));
      } else if (option.connectorId === "okx") {
        available = Boolean(connector) && ready && (hasOkxWallet || Boolean(eipProvider));
      } else if (option.connectorId === "injected") {
        available = Boolean(connector) && ready && hasOtherInjected;
      } else {
        available = Boolean(connector) && ready;
      }

      if (option.id === "trust") {
        const trustAnnounced = hasEip6963Providers
          ? Boolean(eipProvider)
          : hasTrustWallet;
        available = walletConnectEnabled && Boolean(connector) && trustAnnounced;
      }

      // On mobile browsers, only allow wallets we detected (or WalletConnect).
      if (isMobileBrowser && option.connectorId !== "walletConnect") {
        if (option.connectorId === "metaMask") {
          available = available && detectedMetaMask;
        }
        if (option.connectorId === "coinbaseWalletSDK") {
          available = available && detectedCoinbase;
        }
        if (option.connectorId === "rabby") {
          available = available && detectedRabby;
        }
        if (option.connectorId === "okx") {
          available = available && detectedOkx;
        }
        if (option.connectorId === "injected") available = available && hasOtherInjected;
        if (option.id === "trust") {
          available = available && detectedTrust;
        }
      }

      let reason: string | null = null;
      if (!available) {
        if (option.connectorId === "walletConnect" || option.id === "trust") {
          if (!walletConnectEnabled) {
            reason = "Enable WalletConnect";
          } else if (!connector) {
            reason = "Not configured";
          } else if (option.id === "trust" && isMobileBrowser && !detectedTrust) {
            reason = "Not detected";
          } else {
            reason = "Unavailable";
          }
        } else if (!connector) {
          reason = "Not configured";
        } else if (!ready) {
          reason = "Unavailable";
        } else if (isMobileBrowser) {
          reason = "Not detected";
        } else {
          reason = "Install";
        }
      }

      return { option, connector, available, eipProvider, reason };
    });
  }, [connectorsById, hasEip6963Providers, isMobileBrowser, isMounted, providerFlags.providers, resolveEipProvider]);

  const hasAnyAvailable = connectorOptions.some((entry) => entry.available);

  useEffect(() => {
    if (!selectedOption) return;
    const stillAvailable = connectorOptions.some((entry) => entry.option.id === selectedOption.id && entry.available);
    if (!stillAvailable) {
      setSelectedOption(null);
      setAcceptedTerms(false);
    }
  }, [connectorOptions, selectedOption]);

  const isConnecting = connectStatus === "pending";

  useEffect(() => {
    if (!chainMismatch) {
      setSwitchFailure(null);
    }
  }, [chainMismatch]);

  const handleSwitchChain = () => {
    const switchFn = switchChainAsync ?? switchChain;
    if (!switchFn) {
      setSwitchFailure(`Switch to ${defaultChain.name} in your wallet to continue.`);
      return;
    }
    setSwitchFailure(null);
    Promise.resolve(switchFn({ chainId: defaultChain.id })).catch((error: unknown) => {
      setSwitchFailure(
        formatErrorMessage(error instanceof Error ? error : switchError) ??
          `Switch to ${defaultChain.name} to trade.`,
      );
    });
  };
  const closeModal = useCallback(() => {
    setModalOpen(false);
    setSelectedOption(null);
    setAcceptedTerms(false);
    setAutoCloseOnConnect(false);
    setSwitchFailure(null);
  }, []);
  const openModal = () => {
    setModalOpen(true);
    setSelectedOption(null);
    setAcceptedTerms(false);
    setAutoCloseOnConnect(!isConnected);
  };
  const handleConnect = (connector?: Connector, option?: ConnectorOption | null) => {
    if (!connector) {
      console.warn("Connector unavailable for selected wallet option.");
      return;
    }
    setAutoCloseOnConnect(true);
    connect({ connector });
    // Close the selection modal when launching WalletConnect so the QR/modal isn't obstructed.
    if (option?.connectorId === "walletConnect") {
      closeModal();
    }
  };

  useEffect(() => {
    if (isConnected && isModalOpen && autoCloseOnConnect && !chainMismatch) {
      closeModal();
    }
  }, [autoCloseOnConnect, chainMismatch, closeModal, isConnected, isModalOpen]);

  useEffect(() => {
    if (connectStatus === "success" && isModalOpen && autoCloseOnConnect) {
      closeModal();
    }
    if (connectStatus === "error") {
      setAutoCloseOnConnect(false);
    }
  }, [autoCloseOnConnect, closeModal, connectStatus, isModalOpen]);

  const displayAddress = address ?? lastConnectedAddress;
  const displayChainName = chain?.name ?? lastConnectedChainName;
  const buttonLabel = (() => {
    if (isConnecting && !displayAddress) {
      return "Connecting...";
    }
    if (displayAddress) {
      return formatAddress(displayAddress);
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
                {!hasAnyAvailable ? (
                  <p className="rounded-xl border border-white/10 bg-white/5 px-3 py-4 text-center text-xs text-white/70">
                    No compatible wallets detected on this device. Try WalletConnect or switch devices.
                  </p>
                ) : null}
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {connectorOptions.map(({ option, connector, available, reason }) => {
                    const isUnavailable = !available;
                    const disabled = isConnecting || isUnavailable;
                    const isSelected = selectedOption?.id === option.id;
                    const isActiveConnector = isConnected && activeConnectorId === connector?.id;
                    const stateClass = isActiveConnector
                      ? "border-emerald-400 bg-emerald-500/15 ring-1 ring-emerald-300/60"
                      : isSelected
                        ? "border-brand-400 bg-brand-500/20"
                        : isUnavailable
                          ? "border-white/10 bg-white/5 opacity-50 grayscale"
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
                        className={`group flex items-center gap-4 rounded-2xl border px-3 py-3 text-left text-sm font-semibold text-white/90 transition ${isUnavailable ? "text-white/50" : "hover:border-white hover:text-white"} disabled:cursor-not-allowed disabled:opacity-50 ${stateClass}`}
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
                          ) : isUnavailable ? (
                            <span className="mt-1 inline-flex rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-white/50">
                              {reason ?? "Unavailable"}
                            </span>
                          ) : null}
                        </span>
                      </button>
                    );
                  })}
                </div>
                {connectErrorMessage ? <p className="text-xs text-rose-300">{connectErrorMessage}</p> : null}
              </div>
              {selectedOption ? (
                <div className="space-y-4 rounded-2xl border border-white/10 bg-black/30 p-4">
                  <div>
                    <p className="text-base font-semibold text-white">Connect wallet</p>
                    <p className="text-xs uppercase tracking-[0.3em] text-white/50">Terms and Conditions agreement</p>
                  </div>
                  <p className="text-sm text-white/70">
                    By connecting, you agree to the{" "}
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
                    {" "}and acknowledge the risks of using experimental blockchain software.
                  </p>
                  <label className="flex items-start gap-3 text-sm text-white/80">
                    <input
                      type="checkbox"
                      name="termsAccepted"
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
                    onClick={() => handleConnect(connectorsById[selectedOption.connectorId], selectedOption)}
                    className="w-full rounded-2xl bg-brand-500 px-4 py-2.5 text-center text-sm font-semibold text-white transition hover:bg-brand-400 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isConnecting ? "Connecting..." : `Connect with ${selectedOption.label}`}
                  </button>
                </div>
              ) : null}

              {isConnected ? (
                <>
                  {chainMismatch ? (
                    <div className="rounded-2xl border border-amber-300/40 bg-amber-500/10 p-4 text-amber-100">
                      <p className="text-sm font-semibold">Wrong network</p>
                      <p className="text-xs text-amber-50/80">
                        Switch to {defaultChain.name} to continue. Trading is blocked until you change networks in your
                        wallet.
                      </p>
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          onClick={handleSwitchChain}
                          disabled={!switchChain || isSwitching}
                          className="rounded-full border border-white/30 bg-white/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.25em] text-white/90 transition hover:border-white hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {isSwitching ? "Switching..." : `Switch to ${defaultChain.name}`}
                        </button>
                        <span className="text-[11px] text-amber-50/70">
                          If this fails, switch inside your wallet (WalletConnect, MetaMask, Coinbase, injected) then retry.
                        </span>
                      </div>
                      {switchFailure ? <p className="mt-2 text-[11px] text-amber-50/80">{switchFailure}</p> : null}
                    </div>
                  ) : null}
                  <div className="rounded-2xl border border-white/10 bg-black/30 p-4">
                  <div className="flex flex-col gap-2">
                    <p className="text-[11px] uppercase tracking-[0.25em] text-white/50">Connected</p>
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="flex items-center">
                          <p className="font-mono text-sm">{formatAddress(address)}</p>
                          <CopyButton value={address ?? ""} label="Copy wallet address" className="ml-1 text-slate-400" />
                        </div>
                          <p className="text-[11px] text-white/60">{chain?.name ?? "Unknown network"}</p>
                        </div>
                        <div className="flex items-center gap-2">
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

  if (!isMounted) {
    return (
      <div>
        <span className="inline-flex min-w-[9.5rem] items-center justify-center rounded-full bg-brand-500/60 px-5 py-2.5 text-sm font-semibold text-transparent select-none shadow-lg shadow-brand-500/20">
          {lastConnectedAddress ? formatAddress(lastConnectedAddress) : "Connect Wallet"}
        </span>
      </div>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={openModal}
        className="inline-flex min-w-[9.5rem] items-center justify-center gap-3 rounded-full bg-brand-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-brand-500/40 transition hover:bg-brand-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-300"
      >
        {buttonLabel}
      </button>
      {walletModal}
    </div>
  );
}
