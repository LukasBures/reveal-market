import { createConfig, http } from "wagmi";
import { coinbaseWallet, metaMask, walletConnect } from "wagmi/connectors";
import { base } from "wagmi/chains";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://revealmarket.xyz";
const APP_NAME = "Reveal Market";

const chainPresets = {
  base,
} as const;

type PresetChain = (typeof chainPresets)[keyof typeof chainPresets];

function parseChainKeys(value?: string) {
  return (value ?? "base")
    .split(",")
    .map((chain) => chain.trim())
    .filter(Boolean);
}

export function resolveSupportedChains(value?: string): PresetChain[] {
  const requested = parseChainKeys(value);
  const chains = requested
    .map((key) => chainPresets[key as keyof typeof chainPresets])
    .filter((chain): chain is PresetChain => Boolean(chain));
  return chains.length > 0 ? chains : [chainPresets.base];
}

const supportedChains = resolveSupportedChains(process.env.NEXT_PUBLIC_WALLET_CHAINS);

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
