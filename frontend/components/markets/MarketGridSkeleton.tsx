export function MarketGridSkeleton({ cards = 6 }: { cards?: number }) {
  return (
    <div className="grid w-full grid-cols-1 auto-rows-fr gap-4 md:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: cards }).map((_, index) => (
        <div
          key={`skeleton-${index}`}
          className="group relative flex h-full min-h-[170px] w-full animate-pulse flex-col gap-3 overflow-hidden rounded-2xl border border-white/10 bg-white/5 p-3 shadow-[0_25px_60px_rgba(1,3,20,0.65)]"
        >
          <div className="flex items-start gap-3">
            <div className="h-10 w-10 rounded-lg bg-white/10" />
            <div className="flex-1 space-y-2">
              <div className="h-4 w-5/6 rounded bg-white/10" />
              <div className="h-4 w-3/5 rounded bg-white/10" />
              <div className="h-2.5 w-1/3 rounded bg-white/10" />
            </div>
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <div className="h-3 w-2/3 rounded bg-white/10" />
              <div className="h-3 w-12 rounded bg-white/10" />
            </div>
            <div className="flex items-center justify-between">
              <div className="h-3 w-1/2 rounded bg-white/10" />
              <div className="h-3 w-10 rounded bg-white/10" />
            </div>
          </div>
          <div className="mt-auto grid grid-cols-2 gap-2">
            <div className="h-9 rounded-lg bg-white/10" />
            <div className="h-9 rounded-lg bg-white/10" />
          </div>
          <div className="mt-2 flex items-center justify-between">
            <div className="h-3 w-12 rounded bg-white/10" />
            <div className="h-3 w-16 rounded bg-white/10" />
          </div>
        </div>
      ))}
    </div>
  );
}
