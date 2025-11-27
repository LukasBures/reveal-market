import { createConfig, http } from "wagmi";
import type { CreateConnectorFn } from "wagmi";
import { coinbaseWallet, injected, metaMask, walletConnect } from "wagmi/connectors";
import { defineChain } from "viem";
import { ensureLocalStorage } from "@/lib/localStoragePolyfill";

ensureLocalStorage();

const DEFAULT_CHAIN_ID = Number(process.env.NEXT_PUBLIC_CHAIN_ID ?? 2651420);
const DEFAULT_CHAIN_NAME = process.env.NEXT_PUBLIC_CHAIN_NAME ?? "Horizen Testnet";
const DEFAULT_RPC_URL = process.env.NEXT_PUBLIC_RPC_URL ?? "https://horizen-testnet.rpc.caldera.xyz/http";
const DEFAULT_EXPLORER =
  process.env.NEXT_PUBLIC_BLOCK_EXPLORER_URL ?? "https://horizen-testnet.explorer.caldera.xyz";

export const defaultChain = defineChain({
  id: DEFAULT_CHAIN_ID,
  name: DEFAULT_CHAIN_NAME,
  nativeCurrency: { name: "ZEN", symbol: "ZEN", decimals: 18 },
  rpcUrls: {
    default: { http: [DEFAULT_RPC_URL] },
    public: { http: [DEFAULT_RPC_URL] },
  },
  blockExplorers: {
    default: { name: "Explorer", url: DEFAULT_EXPLORER },
  },
});

const chains = [defaultChain] as const;
const walletConnectProjectId =
  process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID || (process.env.NODE_ENV === "test" ? "test" : "");
const walletConnectEnabled = Boolean(walletConnectProjectId);
const resolvedSiteUrl =
  (typeof window !== "undefined" && window.location?.origin) ||
  process.env.NEXT_PUBLIC_SITE_URL ||
  process.env.NEXT_PUBLIC_APP_URL ||
  (process.env.NEXT_PUBLIC_VERCEL_URL ? `https://${process.env.NEXT_PUBLIC_VERCEL_URL}` : "https://revealmarket.xyz");

if (!walletConnectEnabled && typeof console !== "undefined") {
  console.warn("WalletConnect disabled: NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID is not set.");
}

const createWalletConnectors = (): readonly CreateConnectorFn[] => {
  const shared: CreateConnectorFn[] = [metaMask(), injected({ shimDisconnect: true }), coinbaseWallet({ appName: "Reveal Market" })];

  if (walletConnectEnabled) {
    shared.push(
      walletConnect({
        projectId: walletConnectProjectId,
        showQrModal: true,
        metadata: {
          name: "Reveal Market",
          description: "Private prediction markets",
          url: resolvedSiteUrl,
          icons: [new URL("/icon/favicon-96x96.png", resolvedSiteUrl).toString()],
        },
      }),
    );
  }

  return shared as const;
};

export const wagmiConfig = createConfig({
  chains,
  connectors: createWalletConnectors(),
  transports: {
    [defaultChain.id]: http(DEFAULT_RPC_URL),
  },
  ssr: true,
});
