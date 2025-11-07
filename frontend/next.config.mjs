/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
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
        {
          key: 'Cache-Control',
          value: 'public, s-maxage=600, stale-while-revalidate=86400',
        },
      ],
    },
  ],
};

export default nextConfig;
