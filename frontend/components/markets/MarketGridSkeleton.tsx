export function MarketGridSkeleton({ cards = 6 }: { cards?: number }) {
  return (
    <div className="grid auto-rows-fr gap-4 md:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: cards }).map((_, index) => (
        <div
          key={index}
          className="relative flex h-full min-h-[170px] animate-pulse flex-col overflow-hidden rounded-2xl border border-white/10 bg-white/5 shadow-[0_25px_60px_rgba(1,3,20,0.65)]"
        />
      ))}
    </div>
  );
}
