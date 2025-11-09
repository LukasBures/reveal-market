import { notFound } from "next/navigation";
import { fetchFeaturedMarkets, fetchMarketByEventId } from "@/lib/api";
import { MarketDetailHeader } from "@/components/markets/MarketDetailHeader";
import { MarketDetailChart } from "@/components/markets/MarketDetailChart";
import { MarketDetailOutcomes } from "@/components/markets/MarketDetailOutcomes";
import { MarketDetailSidebar } from "@/components/markets/MarketDetailSidebar";
import { MarketDetailMetadata } from "@/components/markets/MarketDetailMetadata";

type MarketDetailParams = {
  eventId: string;
};

type MarketDetailPageProps = {
  params: Promise<MarketDetailParams>;
};

export const dynamicParams = true;

export type GenerateStaticParams = () => Promise<MarketDetailParams[]>;

export const generateStaticParams: GenerateStaticParams = async () => {
  try {
    const markets = await fetchFeaturedMarkets(12);
    return markets
      .map((market) => market.eventId)
      .filter((eventId): eventId is string => Boolean(eventId && eventId !== "unknown"))
      .map((eventId) => ({ eventId }));
  } catch (error) {
    console.error("Unable to prebuild market detail params", error);
    return [];
  }
};

export default async function MarketDetailPage({ params }: MarketDetailPageProps) {
  const { eventId } = await params;
  const market = await fetchMarketByEventId(eventId);
  if (!market) {
    notFound();
  }

  return (
    <div className="bg-gradient-to-b from-slate-950 via-slate-950 to-black text-white">
      <div className="mx-auto flex max-w-6xl flex-col gap-8 px-4 py-10">
        <MarketDetailHeader market={market} />
        <div className="grid gap-6 lg:grid-cols-[2fr,1fr]">
          <div className="space-y-6">
            <MarketDetailChart />
            <MarketDetailOutcomes market={market} />
            <MarketDetailMetadata market={market} />
            <section className="rounded-3xl border border-white/10 bg-slate-900/40 p-6 text-sm text-slate-300">
              <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Market context</p>
              <p className="mt-3">
                {market.extraData?.context ??
                  "This market mirrors Reveal Market’s commit/reveal rails. Settlement proofs are recorded on-chain and mirrored in the backend resolution ledger."}
              </p>
            </section>
          </div>
          <MarketDetailSidebar market={market} />
        </div>
      </div>
    </div>
  );
}
