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
      <div className="mx-auto max-w-7xl px-4 py-16 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
        <div className="space-y-3">
          <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Portfolio</p>
          <h1 className="text-4xl font-semibold text-white">Your positions & claims</h1>
          <p className="text-lg text-slate-300">
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
