import { createConfig, http } from "wagmi";
import { coinbaseWallet, metaMask, walletConnect } from "wagmi/connectors";
import { base } from "wagmi/chains";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://revealmarket.xyz";
const APP_NAME = "Reveal Market";
const DEFAULT_CHAIN_KEYS = (process.env.NEXT_PUBLIC_WALLET_CHAINS ?? "base")
  .split(",")
  .map((chain) => chain.trim())
  .filter(Boolean);

const supportedChains = [base] as const;

const projectId = process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID ?? "";
const runtimeOrigin =
  typeof window !== "undefined" && typeof window.location !== "undefined" ? window.location.origin : null;
const metadataUrl = runtimeOrigin || SITE_URL;
const iconBase = runtimeOrigin?.startsWith("http") ? runtimeOrigin : SITE_URL;
const iconUrl = `${iconBase.replace(/\/$/, "")}/wallet-icon.svg`;

const walletMetadata = {
  name: APP_NAME,
  description: "Institutional-grade prediction markets with zk-settlement.",
  url: metadataUrl,
  icons: [iconUrl],
};

export const wagmiConfig = createConfig({
  chains: supportedChains,
  ssr: true,
  connectors: [
    metaMask({
      dappMetadata: walletMetadata,
      useDeeplink: true,
    }),
    walletConnect({
      projectId: projectId || "00000000000000000000000000000000",
      showQrModal: true,
      metadata: walletMetadata,
    }),
    coinbaseWallet({
      appName: APP_NAME,
      appLogoUrl: iconUrl,
      reloadOnDisconnect: false,
    }),
  ],
  transports: supportedChains.reduce(
    (acc, chain) => ({
      ...acc,
      [chain.id]: http(),
    }),
    {} as Record<number, ReturnType<typeof http>>,
  ),
});

export const primaryChain = supportedChains[0];
