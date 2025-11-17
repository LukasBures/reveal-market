import { createConfig, http } from "wagmi";
import { coinbaseWallet, metaMask, walletConnect, injected } from "wagmi/connectors";
import { base } from "wagmi/chains";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://revealmarket.xyz";
const APP_NAME = "Reveal Market";

const chainPresets = {
  base,
} as const;

type PresetChain = (typeof chainPresets)[keyof typeof chainPresets];
type SupportedChainList = readonly [PresetChain, ...PresetChain[]];

function parseChainKeys(value?: string) {
  return (value ?? "base")
    .split(",")
    .map((chain) => chain.trim())
    .filter(Boolean);
}

function ensureChainList(chains: PresetChain[]): SupportedChainList {
  if (chains.length === 0) {
    return [chainPresets.base];
  }
  const [first, ...rest] = chains;
  return [first, ...rest] as SupportedChainList;
}

export function resolveSupportedChains(value?: string): SupportedChainList {
  const requested = parseChainKeys(value);
  const chains = requested
    .map((key) => chainPresets[key as keyof typeof chainPresets])
    .filter((chain): chain is PresetChain => Boolean(chain));
  return ensureChainList(chains);
}

const supportedChains = resolveSupportedChains(process.env.NEXT_PUBLIC_WALLET_CHAINS);

const projectId = process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID ?? "";
export const walletConnectEnabled = Boolean(projectId);
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

const baseConnectors = [
  injected({
    shimDisconnect: true,
  }),
  metaMask({
    dappMetadata: walletMetadata,
    useDeeplink: true,
  }),
  coinbaseWallet({
    appName: APP_NAME,
    appLogoUrl: iconUrl,
    reloadOnDisconnect: false,
  }),
] as const;

const connectors = walletConnectEnabled
  ? [
      ...baseConnectors,
      walletConnect({
        projectId,
        showQrModal: true,
        metadata: walletMetadata,
        qrModalOptions: {
          themeVariables: {
            "--wcm-accent-color": "#7bf05e",
            "--wcm-background-color": "#010314",
          },
        },
      }),
    ]
  : baseConnectors;

export const wagmiConfig = createConfig({
  chains: supportedChains,
  ssr: true,
  connectors,
  transports: supportedChains.reduce(
    (acc, chain) => ({
      ...acc,
      [chain.id]: http(),
    }),
    {} as Record<number, ReturnType<typeof http>>,
  ),
});

export const primaryChain = supportedChains[0];
