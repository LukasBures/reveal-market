import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Manrope } from "next/font/google";

import "./globals.css";

import { AppProviders } from "@/components/providers/AppProviders";
import { MainNav } from "@/components/layout/MainNav";
import { Footer } from "@/components/layout/Footer";

const font = Manrope({
  subsets: ["latin"],
  variable: "--font-sans",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://revealmarket.xyz"),
  title: {
    default: "Reveal Market",
    template: "%s | Reveal Market",
  },
  description:
    "Zero-knowledge commit-and-reveal prediction markets with a fast FastAPI backend and Foundry contracts.",
  openGraph: {
    title: "Reveal Market",
    description:
      "Zero-knowledge prediction markets with a battle-tested backend and wallet-ready frontend.",
    url: "https://revealmarket.xyz",
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
      </body>
    </html>
  );
}
