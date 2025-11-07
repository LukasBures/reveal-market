import { fetchFeaturedMarkets } from "@/lib/api";
import { MarketsPreviewClient } from "./MarketsPreview";

export async function MarketsSection() {
  const markets = await fetchFeaturedMarkets(6);

  return (
    <section className="mx-auto max-w-6xl px-4 py-10">
      <div className="mb-6 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm uppercase tracking-[0.3em] text-slate-400">
            Live markets
          </p>
          <h2 className="text-2xl font-semibold text-white">
            Top liquidity opportunities
          </h2>
        </div>
        <p className="text-sm text-slate-400">
          Data refreshes automatically from the FastAPI backend.
        </p>
      </div>
      <MarketsPreviewClient initialMarkets={markets} />
    </section>
  );
}
