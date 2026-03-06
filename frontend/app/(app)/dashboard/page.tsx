import type { Metadata } from "next";
import dynamic from "next/dynamic";
import { buildBreadcrumbJsonLd, buildMetadata } from "@/lib/seo";
import { JsonLd } from "@/components/seo/JsonLd";

const DashboardClient = dynamic(
  () => import("@/components/dashboard/DashboardClient").then((mod) => ({ default: mod.DashboardClient })),
  {
    loading: () => (
      <div className="rounded-3xl border border-white/10 bg-slate-950/40 p-6 text-center text-slate-300">
        Loading your dashboard...
      </div>
    ),
  },
);

export const metadata: Metadata = buildMetadata({
  title: "Your Positions | Reveal Market",
  description: "Track your escrow balance, open positions, potential payouts, and claims.",
  path: "/dashboard",
  keywords: ["positions", "escrow", "claims", "reveal market"],
  robots: { index: false, follow: false },
});

export default function DashboardPage() {
  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Dashboard", path: "/dashboard" },
  ]);
  return (
    <>
      <div className="relative mx-auto max-w-7xl px-4 py-12 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] sm:py-16">
        {/* ambient page glows — brand violet top-left, brand green top-right */}
        <div aria-hidden="true" className="pointer-events-none absolute -top-32 left-1/4 h-80 w-[600px] -translate-x-1/2 rounded-full bg-[rgba(124,132,255,0.08)] blur-3xl" />
        <div aria-hidden="true" className="pointer-events-none absolute -top-16 right-0 h-56 w-96 rounded-full bg-[rgba(123,240,94,0.05)] blur-3xl" />
        <div className="space-y-3">
          <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Portfolio</p>
          <h1 className="text-3xl font-semibold text-white [text-shadow:0_0_48px_rgba(124,132,255,0.35)] sm:text-4xl">Your positions & claims</h1>
          <p className="text-base text-slate-300 sm:text-lg">
            Review your escrow balance, open tickets, potential payouts, and claim winnings once markets settle.
          </p>
        </div>
        <div className="mt-10">
          <DashboardClient />
        </div>
      </div>
      <JsonLd data={breadcrumbs} id="dashboard-breadcrumbs" />
    </>
  );
}
