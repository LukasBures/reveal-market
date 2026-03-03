import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { Manrope } from "next/font/google";
import localFont from "next/font/local";
import Script from "next/script";
import { Toaster } from "sonner";
import "./globals.css";

import "@/lib/suppressLocalStorageWarning";
import { absoluteUrl } from "@/lib/seo";
import { serverEnv } from "@/lib/serverEnv";
import { AppProviders } from "@/components/providers/AppProviders";
import { HeartbeatClient } from "@/components/providers/HeartbeatClient";
import { MainNav } from "@/components/layout/MainNav";
import { Footer } from "@/components/layout/Footer";

export const revalidate = 60;

const font = Manrope({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});
const displayFont = localFont({
  src: "./fonts/AutobusBold.ttf",
  variable: "--font-display",
  weight: "400",
});

const SITE_URL = absoluteUrl("/");
const SEARCH_URL = absoluteUrl("/search");
const IS_PRODUCTION = process.env.NODE_ENV === "production";
const GA_MEASUREMENT_ID = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID;
const SHOULD_LOAD_GA = IS_PRODUCTION && GA_MEASUREMENT_ID;
const GA_SAMPLE_RATE = (() => {
  const raw = process.env.NEXT_PUBLIC_GA_SAMPLE_RATE;
  if (!raw) return 50;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return 50;
  return Math.min(Math.max(parsed, 1), 100);
})();
const SHOULD_SUPPRESS_LIT_WARNING = true;
const isBrowserResolvableHost = (hostname: string) => {
  const normalized = hostname.toLowerCase();
  // Treat dotted domains or IPv6 literals as routable; skip bare Docker hostnames like "api".
  return normalized.includes(".") || normalized.includes(":");
};
const API_ORIGIN = (() => {
  const candidate = serverEnv.apiBaseUrl;
  try {
    const url = new URL(candidate);
    return isBrowserResolvableHost(url.hostname) ? url.origin : null;
  } catch {
    return null;
  }
})();

const organizationJsonLd = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: "Reveal Market",
  url: SITE_URL,
  logo: absoluteUrl("/opengraph-image"),
  sameAs: ["https://x.com/RevealMarket"],
  contactPoint: [
    {
      "@type": "ContactPoint",
      contactType: "Partnerships",
      url: absoluteUrl("/contact"),
    },
  ],
};

const websiteJsonLd = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "Reveal Market",
  url: SITE_URL,
  potentialAction: {
    "@type": "SearchAction",
    target: `${SEARCH_URL}?q={search_term_string}`,
    "query-input": "required name=search_term_string",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  themeColor: "#2735d2",
};

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Reveal Market",
    template: "%s | Reveal Market",
  },
  description: "Private prediction markets that keep entries private while events play out and publish clear settlement receipts.",
  keywords: ["reveal market", "prediction markets", "private markets", "institutional trading"],
  robots: {
    index: true,
    follow: true,
    "max-image-preview": "large",
    "max-snippet": -1,
    "max-video-preview": -1,
    googleBot: {
      index: true,
      follow: true,
      "max-image-preview": "large",
      "max-snippet": -1,
      "max-video-preview": -1,
    },
  },
  openGraph: {
    title: "Reveal Market",
    description: "Private prediction markets where your entries stay private until outcomes settle and receipts post.",
    url: SITE_URL,
    siteName: "Reveal Market",
    images: [
      {
        url: "/opengraph-image",
        width: 1200,
        height: 630,
        alt: "Reveal Market preview",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    creator: "@RevealMarket",
  },
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${font.variable} ${displayFont.variable}`}>
      <head>
        {SHOULD_SUPPRESS_LIT_WARNING ? (
          <Script id="lit-warnings" strategy="beforeInteractive">
            {`
              globalThis.litIssuedWarnings ??= new Set();
              globalThis.litIssuedWarnings.add('dev-mode');
            `}
          </Script>
        ) : null}
        <link rel="preconnect" href="https://fonts.googleapis.com" crossOrigin="anonymous" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        {API_ORIGIN ? <link rel="preconnect" href={API_ORIGIN} crossOrigin="anonymous" /> : null}
        <link rel="icon" type="image/png" href="/favicon-96x96.png" sizes="96x96" />
        <link rel="icon" type="image/png" href="/favicon-32x32.png" sizes="32x32" />
        <link rel="icon" type="image/png" href="/favicon-16x16.png" sizes="16x16" />
        <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
        <link rel="icon" href="/favicon.ico" sizes="any" />
        <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png" />
        <link rel="mask-icon" href="/safari-pinned-tab.svg" color="#2735d2" />
        <meta name="apple-mobile-web-app-title" content="Reveal Market" />
        <link rel="manifest" href="/site.webmanifest" />
        <script
          type="application/ld+json"
          suppressHydrationWarning
          dangerouslySetInnerHTML={{ __html: JSON.stringify(organizationJsonLd) }}
        />
        <script
          type="application/ld+json"
          suppressHydrationWarning
          dangerouslySetInnerHTML={{ __html: JSON.stringify(websiteJsonLd) }}
        />
      </head>
      <body
        className="text-white antialiased px-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]"
        suppressHydrationWarning
      >
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:z-[100] focus:top-4 focus:left-4 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:text-black focus:font-semibold focus:shadow-lg"
        >
          Skip to main content
        </a>
        <AppProviders>
          <HeartbeatClient />
          <div className="flex min-h-screen flex-col">
            <MainNav />
            <main id="main-content" className="flex-1 flex flex-col">{children}</main>
            <Footer />
          </div>
        </AppProviders>
        {SHOULD_LOAD_GA ? (
          <>
            <Script
              src={`https://www.googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}`}
              strategy="afterInteractive"
            />
            <Script id="gtag-init" strategy="afterInteractive">
              {`
                window.dataLayer = window.dataLayer || [];
                function gtag(){dataLayer.push(arguments);}
                gtag('js', new Date());
                gtag('config', '${GA_MEASUREMENT_ID}', {
                  sample_rate: ${GA_SAMPLE_RATE},
                  anonymize_ip: true
                });
              `}
            </Script>
          </>
        ) : null}
        <Toaster theme="dark" position="bottom-right" richColors />
      </body>
    </html>
  );
}
