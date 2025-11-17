import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Manrope } from "next/font/google";
import localFont from "next/font/local";
import Script from "next/script";
import { cookies } from "next/headers";

import "./globals.css";

import { AppProviders } from "@/components/providers/AppProviders";
import { HeartbeatClient } from "@/components/providers/HeartbeatClient";
import { MainNav } from "@/components/layout/MainNav";
import { Footer } from "@/components/layout/Footer";
import { absoluteUrl } from "@/lib/seo";
import { logger } from "@/lib/logging";
import { LandingGate } from "@/components/landing/LandingGate";
import {
  LANDING_ACCESS_COOKIE_NAME,
  isLandingGateEnabled,
} from "@/lib/access-gate";

export const dynamic = "force-dynamic";

const font = Manrope({
  subsets: ["latin"],
  variable: "--font-sans",
});
const displayFont = localFont({
  src: "./fonts/AutobusBold.ttf",
  variable: "--font-display",
  weight: "400",
});

const SITE_URL = absoluteUrl("/");
const IS_PRODUCTION = process.env.NODE_ENV === "production";
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  process.env.RM_API_BASE_URL ??
  "http://localhost:8000";
const API_ORIGIN = (() => {
  try {
    return new URL(API_BASE).origin;
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
      email: "hello@revealmarket.xyz",
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
    target: `${SITE_URL}?q={search_term_string}`,
    "query-input": "required name=search_term_string",
  },
};

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Reveal Market",
    template: "%s | Reveal Market",
  },
  description:
    "Zero-knowledge commit-and-reveal prediction markets with a fast FastAPI backend and Foundry contracts.",
  keywords: [
    "reveal market",
    "prediction markets",
    "zero knowledge",
    "institutional trading",
  ],
  robots: {
    index: true,
    follow: true,
  },
  openGraph: {
    title: "Reveal Market",
    description:
      "Zero-knowledge prediction markets with a battle-tested backend and wallet-ready frontend.",
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
  logger.info("Rendering RootLayout", {
    route: "app/layout",
    nodeEnv: process.env.NODE_ENV,
  });
  const cookieStore = await cookies();
  const hasLandingAccess = cookieStore.get(LANDING_ACCESS_COOKIE_NAME)?.value === "granted";
  const gateEnabled = isLandingGateEnabled();
  const showProtectedApp = !gateEnabled || hasLandingAccess;
  return (
    <html lang="en" className={`${font.variable} ${displayFont.variable}`}>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" crossOrigin="anonymous" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        {API_ORIGIN ? <link rel="preconnect" href={API_ORIGIN} crossOrigin="anonymous" /> : null}
        <link rel="icon" type="image/png" href="/favicon-96x96.png" sizes="96x96" />
        <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
        <link rel="shortcut icon" href="/favicon.ico" />
        <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png" />
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
      <body className="text-white antialiased">
        <AppProviders>
          {showProtectedApp ? (
            <>
              <HeartbeatClient />
              <div className="flex min-h-screen flex-col">
                <MainNav />
                <main className="flex-1">{children}</main>
                <Footer />
              </div>
            </>
          ) : (
            <LandingGate />
          )}
        </AppProviders>
        {IS_PRODUCTION ? (
          <>
            <Script
              src="https://www.googletagmanager.com/gtag/js?id=G-MXPV8T1V5K"
              strategy="afterInteractive"
            />
            <Script id="gtag-init" strategy="afterInteractive">
              {`
                window.dataLayer = window.dataLayer || [];
                function gtag(){dataLayer.push(arguments);}
                gtag('js', new Date());
                gtag('config', 'G-MXPV8T1V5K');
              `}
            </Script>
          </>
        ) : null}
      </body>
    </html>
  );
}
