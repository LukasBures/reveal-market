const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'https://api.revealmarket.xyz';

const GA_ORIGINS = [
  "https://www.googletagmanager.com",
  "https://www.google-analytics.com",
  "https://region1.google-analytics.com",
];

const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline' ${GA_ORIGINS.join(" ")}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: https:",
  "font-src 'self' data:",
  `connect-src 'self' ${API_BASE} ${GA_ORIGINS.join(" ")}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join('; ');

const securityHeaders = [
  { key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains; preload' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'no-referrer' },
  { key: 'Permissions-Policy', value: 'geolocation=(), camera=(), microphone=()' },
  { key: 'Cross-Origin-Resource-Policy', value: 'same-site' },
  { key: 'Cross-Origin-Opener-Policy', value: 'same-origin' },
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
      { protocol: 'https', hostname: '*.cloudfront.net' },
    ],
  },
  experimental: {
    typedRoutes: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
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
