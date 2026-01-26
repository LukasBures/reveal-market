import { MarketGridSkeleton } from "@/components/markets/MarketGridSkeleton";
import { Skeleton } from "@/components/ui/Skeleton";

export default function MarketDetailLoading() {
  return (
    <div className="bg-gradient-to-b from-slate-950 via-slate-950 to-black text-white">
      <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-16 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
        <section className="grid gap-6 lg:grid-cols-[1.7fr,1fr]">
          <div className="space-y-4">
            <Skeleton className="h-10 w-3/4 rounded-2xl bg-white/10" />
            <Skeleton className="h-60 rounded-3xl border border-white/10 bg-white/5" />
            <MarketGridSkeleton />
          </div>
          <div className="space-y-4">
            <Skeleton className="h-72 rounded-3xl border border-white/10 bg-white/5" />
            <Skeleton className="h-40 rounded-3xl border border-white/10 bg-white/5" />
          </div>
        </section>
      </div>
    </div>
  );
}
