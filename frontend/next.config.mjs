import path from "node:path";
import { PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD, PHASE_PRODUCTION_SERVER } from "next/constants.js";

const RM_ENV = (process.env.RM_ENVIRONMENT ?? process.env.NODE_ENV ?? "development").toLowerCase();
const IS_PROD_MODE = RM_ENV.includes("prod");
const DEFAULT_API_BASE = IS_PROD_MODE ? "https://api.revealmarket.xyz" : "http://localhost:8000";
const DEFAULT_STREAMER_BASE = IS_PROD_MODE ? "https://stream.revealmarket.xyz" : "http://localhost:8100";
const API_BASE = DEFAULT_API_BASE.replace(/\/$/, "");
const STREAMER_BASE = DEFAULT_STREAMER_BASE.replace(/\/$/, "");
const STREAMER_WS = STREAMER_BASE.replace(/^http/i, "ws");
const DEFAULT_RPC_URL = "https://horizen-testnet.rpc.caldera.xyz/http";
const PROD_API_BASE = "https://api.revealmarket.xyz";
const PROD_STREAMER_BASE = "https://stream.revealmarket.xyz";
const PROD_STREAMER_WS = PROD_STREAMER_BASE.replace(/^http/i, "ws");
const DISABLE_MINIFY = process.env.NEXT_DISABLE_MINIFY === "true";
const TURNSTILE_ORIGIN = "https://challenges.cloudflare.com";

const GA_ORIGINS = [
  "https://www.googletagmanager.com",
  "https://www.google-analytics.com",
  "https://region1.google-analytics.com",
];

const styleSrc = ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"];
const fontSrc = ["'self'", "data:", "https://fonts.gstatic.com", "https://fonts.reown.com"];
const WALLET_PROVIDER_ORIGINS = [
  // Base RPC + optional providers
  "https://mainnet.base.org",
  "https://*.alchemy.com",
  "https://*.infura.io",
  "https://rpc.ankr.com",
  // MetaMask telemetry used by their SDK
  "https://metamask-sdk.api.cx.metamask.io",
  "https://mm-sdk-analytics.api.cx.metamask.io",
  // Coinbase Wallet endpoints (app + analytics)
  "https://wallet.coinbase.com",
  "https://www.walletlink.org",
  "https://api.wallet.coinbase.com",
  "https://avatars.coinbase.com",
  "https://cca-lite.coinbase.com",
  "https://cca.coinbase.com",
  // WalletConnect infrastructure + explorer
  "https://*.walletconnect.com",
  "https://relay.walletconnect.com",
  "https://registry.walletconnect.com",
  "https://explorer-api.walletconnect.com",
  "https://cloud.walletconnect.com",
  "https://*.walletconnect.cloud",
  "https://cdn.walletconnect.com",
  "https://images.walletconnect.com",
  "https://walletconnect.org",
  "https://walletconnect.com",
  "https://api.web3modal.org",
  "https://pulse.walletconnect.org",
];
const WALLET_PROVIDER_WS = [
  "wss://relay.walletconnect.com",
  "wss://relay.walletconnect.org",
  "wss://*.walletconnect.com",
  "wss://*.walletconnect.org",
  "wss://metamask-sdk.api.cx.metamask.io",
  "wss://www.walletlink.org",
];

const walletFrameOrigins = [
  "https://verify.walletconnect.org",
  "https://*.walletconnect.com",
  "https://wallet.coinbase.com",
];

const rpcOrigins = Array.from(
  new Set(
    [process.env.NEXT_PUBLIC_RPC_URL, DEFAULT_RPC_URL]
      .map((candidate) => (candidate ?? "").trim())
      .filter(Boolean)
      .map((rawUrl) => {
        try {
          return new URL(rawUrl).origin;
        } catch (err) {
          console.warn(`Invalid RPC URL for CSP: ${rawUrl}`);
          return null;
        }
      })
      .filter(Boolean),
  ),
);

/** @type {import('next').NextConfig} */
const nextConfig = (phase) => {
  const isDev = phase === PHASE_DEVELOPMENT_SERVER;
  const isProd = phase === PHASE_PRODUCTION_BUILD || phase === PHASE_PRODUCTION_SERVER;
  const shouldMinify = !(DISABLE_MINIFY && isProd);

  const scriptSrc = ["'self'", "'unsafe-inline'"];
  scriptSrc.push(TURNSTILE_ORIGIN);
  if (isDev) {
    // React Fast Refresh relies on eval-like constructs in dev. Restrict to the dev server phase
    // so production CSP stays strict even if NODE_ENV is mis-set.
    scriptSrc.push("'unsafe-eval'");
  }

  const connectSrc = [
    "'self'",
    API_BASE,
    STREAMER_BASE,
    STREAMER_WS,
    PROD_API_BASE,
    PROD_STREAMER_BASE,
    PROD_STREAMER_WS,
    TURNSTILE_ORIGIN,
    ...WALLET_PROVIDER_ORIGINS,
    ...WALLET_PROVIDER_WS,
    ...rpcOrigins,
  ];
  if (isDev) {
    connectSrc.push("http://localhost:8000", "http://localhost:8100", "ws://localhost:8100");
  }
  if (isProd) {
    scriptSrc.push(...GA_ORIGINS);
    connectSrc.push(...GA_ORIGINS);
  }

  const csp = [
    "default-src 'self'",
    `script-src ${scriptSrc.join(" ")}`,
    `style-src ${styleSrc.join(" ")}`,
    "img-src 'self' data: https: blob:",
    `font-src ${fontSrc.join(" ")}`,
    `connect-src ${connectSrc.join(" ")}`,
    `frame-src 'self' ${walletFrameOrigins.join(" ")} ${TURNSTILE_ORIGIN}`,
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");

  const securityHeaders = [
    { key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains; preload' },
    { key: 'X-Frame-Options', value: 'DENY' },
    { key: 'X-Content-Type-Options', value: 'nosniff' },
    { key: 'Referrer-Policy', value: 'no-referrer' },
    { key: 'Permissions-Policy', value: 'geolocation=(), camera=(), microphone=()' },
    { key: 'Cross-Origin-Resource-Policy', value: 'same-site' },
    { key: 'Cross-Origin-Opener-Policy', value: 'same-origin-allow-popups' },
    { key: 'X-DNS-Prefetch-Control', value: 'off' },
    { key: 'Content-Security-Policy', value: csp },
  ];

  return {
    reactStrictMode: true,
    output: 'standalone',
    productionBrowserSourceMaps: false,
    images: {
      unoptimized: true,
      remotePatterns: [
        { protocol: 'https', hostname: 'images.revealmarket.xyz' },
        { protocol: 'https', hostname: 'cdn.revealmarket.xyz' },
        { protocol: 'https', hostname: '*.polymarket.com' },
        { protocol: 'https', hostname: 'polymarket-upload.s3.us-east-2.amazonaws.com' },
        { protocol: 'https', hostname: '*.cloudfront.net' },
      ],
    },
    typedRoutes: true,
    eslint: {
      ignoreDuringBuilds: true,
    },
    webpack: (config) => {
      if (!shouldMinify) {
        config.optimization = config.optimization ?? {};
        config.optimization.minimize = false;
        config.optimization.minimizer = [];
      }
      config.resolve = config.resolve ?? {};
      config.resolve.alias = config.resolve.alias ?? {};
      config.resolve.alias["@react-native-async-storage/async-storage"] = path.resolve(
        process.cwd(),
        "lib/wallet/asyncStorageShim.ts",
      );
      return config;
    },
    headers: async () => [
      {
        source: '/docs/:path*',
        headers: [
          ...securityHeaders,
          {
            key: 'Cache-Control',
            value: 'public, s-maxage=600, stale-while-revalidate=86400',
          },
        ],
      },
      {
        source: '/:path*',
        headers: securityHeaders,
      },
    ],
  };
};

export default nextConfig;
