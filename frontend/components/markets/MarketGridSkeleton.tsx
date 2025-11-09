export function MarketGridSkeleton({ cards = 6 }: { cards?: number }) {
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: cards }).map((_, index) => (
        <div
          key={index}
          className="h-52 animate-pulse rounded-3xl border border-white/5 bg-white/5"
        />
      ))}
    </div>
  );
}
