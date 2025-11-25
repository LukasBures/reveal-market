import { createConfig, http } from "wagmi";
import type { CreateConnectorFn } from "wagmi";
import { base } from "wagmi/chains";
import { coinbaseWallet, injected, metaMask, walletConnect } from "wagmi/connectors";

const chains = [base] as const;
const walletConnectProjectId = process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID;
const siteUrl =
  process.env.NEXT_PUBLIC_SITE_URL ??
  process.env.NEXT_PUBLIC_APP_URL ??
  (process.env.NEXT_PUBLIC_VERCEL_URL ? `https://${process.env.NEXT_PUBLIC_VERCEL_URL}` : "https://revealmarket.xyz");

if (!walletConnectProjectId) {
  throw new Error("NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID must be defined.");
}

const createWalletConnectors = (): readonly CreateConnectorFn[] => {
  const shared = [
    coinbaseWallet({ appName: "Reveal Market" }),
    walletConnect({
      projectId: walletConnectProjectId,
      showQrModal: true,
      metadata: {
        name: "Reveal Market",
        description: "Private prediction markets",
        url: siteUrl,
        icons: [new URL("/icon/favicon-96x96.png", siteUrl).toString()],
      },
    }),
  ] as const;

  if (typeof window === "undefined") {
    return shared;
  }

  return [
    metaMask(),
    injected({ shimDisconnect: true }),
    ...shared,
  ] as const;
};

export const wagmiConfig = createConfig({
  chains,
  connectors: createWalletConnectors(),
  transports: {
    [base.id]: http(),
  },
  ssr: true,
});
