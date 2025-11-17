import path from "node:path";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://api.revealmarket.xyz";
const IS_PRODUCTION = process.env.NODE_ENV === "production";

const GA_ORIGINS = [
  "https://www.googletagmanager.com",
  "https://www.google-analytics.com",
  "https://region1.google-analytics.com",
];

const scriptSrc = ["'self'", "'unsafe-inline'"];
const WALLET_PROVIDER_ORIGINS = [
  "https://mm-sdk-analytics.api.cx.metamask.io",
  "https://wallet.coinbase.com",
  "https://cca-lite.coinbase.com",
  "https://cca.coinbase.com",
];
const connectSrc = ["'self'", API_BASE, ...WALLET_PROVIDER_ORIGINS];
if (IS_PRODUCTION) {
  scriptSrc.push(...GA_ORIGINS);
  connectSrc.push(...GA_ORIGINS);
}

const csp = [
  "default-src 'self'",
  `script-src ${scriptSrc.join(" ")}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: https:",
  "font-src 'self' data:",
  `connect-src ${connectSrc.join(" ")}`,
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

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: 'images.revealmarket.xyz' },
      { protocol: 'https', hostname: 'cdn.revealmarket.xyz' },
      { protocol: 'https', hostname: '*.polymarket.com' },
      { protocol: 'https', hostname: 'polymarket-upload.s3.us-east-2.amazonaws.com' },
      { protocol: 'https', hostname: '*.cloudfront.net' },
    ],
  },
  experimental: {
    typedRoutes: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
  webpack: (config) => {
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

export default nextConfig;
