import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Manrope } from "next/font/google";

import "./globals.css";

import { AppProviders } from "@/components/providers/AppProviders";
import { MainNav } from "@/components/layout/MainNav";
import { Footer } from "@/components/layout/Footer";
import { absoluteUrl } from "@/lib/seo";

const font = Manrope({
  subsets: ["latin"],
  variable: "--font-sans",
});

const SITE_URL = absoluteUrl("/");

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
  alternates: {
    canonical: SITE_URL,
  },
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

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={font.variable}>
      <body className="bg-[#030712] text-white antialiased">
        <AppProviders>
          <div className="flex min-h-screen flex-col">
            <MainNav />
            <main className="flex-1">{children}</main>
            <Footer />
          </div>
        </AppProviders>
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
      </body>
    </html>
  );
}
