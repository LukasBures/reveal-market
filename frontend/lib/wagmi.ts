import { createConfig, http } from "wagmi";
import type { Config, CreateConnectorFn } from "wagmi";
import { coinbaseWallet, injected, walletConnect } from "wagmi/connectors";
import { defineChain } from "viem";
import { ensureLocalStorage } from "@/lib/localStoragePolyfill";
import { logger } from "@/lib/logging";
import { resolveUrlConfig } from "@/lib/env-presets";

ensureLocalStorage();

// Prevent HMR from re-initializing WalletConnect multiple times.
const globalState = globalThis as typeof globalThis & {
  __wagmiConfig?: Config;
  __wagmiWalletConnectors?: CreateConnectorFn[];
};

const EXPECTED_CHAIN_ID = 2651420;
const FALLBACK_CHAIN_NAME = "Horizen Testnet";
const FALLBACK_RPC_URL = "https://horizen-testnet.rpc.caldera.xyz/http";
const FALLBACK_EXPLORER = "https://horizen-testnet.explorer.caldera.xyz";

const parseChainId = (raw?: string | number | null): number | null => {
  if (raw === undefined || raw === null) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
};

const resolvedEnvChainId = parseChainId(process.env.NEXT_PUBLIC_CHAIN_ID);
const chainId =
  resolvedEnvChainId === EXPECTED_CHAIN_ID ? resolvedEnvChainId : EXPECTED_CHAIN_ID;
if (resolvedEnvChainId === null) {
  logger.warn("wagmi.chain_id_missing", {
    provided_chain_id: process.env.NEXT_PUBLIC_CHAIN_ID ?? null,
    fallback_chain_id: EXPECTED_CHAIN_ID,
  });
} else if (resolvedEnvChainId !== EXPECTED_CHAIN_ID) {
  logger.warn("wagmi.chain_id_mismatch", {
    provided_chain_id: resolvedEnvChainId,
    fallback_chain_id: EXPECTED_CHAIN_ID,
  });
}

const chainName = process.env.NEXT_PUBLIC_CHAIN_NAME || FALLBACK_CHAIN_NAME;
const rpcUrl = process.env.NEXT_PUBLIC_RPC_URL || FALLBACK_RPC_URL;
const explorerUrl = process.env.NEXT_PUBLIC_BLOCK_EXPLORER_URL || FALLBACK_EXPLORER;
if (!process.env.NEXT_PUBLIC_RPC_URL) {
  logger.warn("wagmi.rpc_url_missing", { fallback_rpc_url: FALLBACK_RPC_URL });
}
if (!process.env.NEXT_PUBLIC_BLOCK_EXPLORER_URL) {
  logger.warn("wagmi.explorer_missing", { fallback_explorer_url: FALLBACK_EXPLORER });
}

export const defaultChain = defineChain({
  id: chainId,
  name: chainName,
  nativeCurrency: { name: "Zen", symbol: "ZEN", decimals: 18 },
  rpcUrls: {
    default: { http: [rpcUrl] },
    public: { http: [rpcUrl] },
  },
  blockExplorers: {
    default: { name: "Explorer", url: explorerUrl },
  },
});

const chains = [defaultChain] as const;
const walletConnectProjectId =
  process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID || (process.env.NODE_ENV === "test" ? "test" : "");
const walletConnectEnabled = Boolean(walletConnectProjectId);
const isTestEnv =
  process.env.NODE_ENV === "test" ||
  process.env.VITEST === "true" ||
  process.env.VITEST === "1" ||
  Boolean(process.env.VITEST_WORKER_ID);
const resolvedSiteUrl =
  (typeof window !== "undefined" && window.location?.origin) || resolveUrlConfig().siteUrl || "https://revealmarket.xyz";

if (!walletConnectEnabled && !isTestEnv && typeof console !== "undefined") {
  console.warn("WalletConnect disabled: NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID is not set.");
}

const createWalletConnectors = (): CreateConnectorFn[] => {
  const shared: CreateConnectorFn[] = [
    injected({ target: "metaMask", shimDisconnect: true }),
    injected({ shimDisconnect: true }),
    coinbaseWallet({ appName: "Reveal Market" }),
  ];

  if (walletConnectEnabled) {
    shared.push(
      walletConnect({
        projectId: walletConnectProjectId,
        showQrModal: true,
        metadata: {
          name: "Reveal Market",
          description: "Private prediction markets",
          url: resolvedSiteUrl,
          icons: [new URL("/icons/favicon-96x96.png", resolvedSiteUrl).toString()],
        },
      }),
    );
  }

  return shared;
};

const getWalletConnectors = (): CreateConnectorFn[] => {
  if (globalState.__wagmiWalletConnectors) {
    return globalState.__wagmiWalletConnectors;
  }
  const connectors = createWalletConnectors();
  globalState.__wagmiWalletConnectors = connectors;
  return connectors;
};

const buildWagmiConfig = (): Config =>
  createConfig({
    chains,
    connectors: getWalletConnectors(),
    transports: {
      [defaultChain.id]: http(rpcUrl),
    },
    ssr: true,
  });

export const wagmiConfig: Config = globalState.__wagmiConfig ?? (globalState.__wagmiConfig = buildWagmiConfig());
