export function MarketGridSkeleton({ cards = 6 }: { cards?: number }) {
  return (
    <div className="grid w-full grid-cols-1 auto-rows-fr gap-4 md:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: cards }).map((_, index) => (
        <div
          key={`skeleton-${index}`}
          className="group relative flex h-[256px] w-full animate-pulse flex-col gap-3 overflow-hidden rounded-2xl border border-white/10 bg-white/5 p-3 shadow-[0_25px_60px_rgba(1,3,20,0.65)]"
        >
          <div className="flex items-start gap-3">
            <div className="h-10 w-10 shrink-0 rounded-lg" />
            <div className="min-w-0 flex-1">
              <div className="min-h-[3rem]" />
            </div>
          </div>
          <div className="mt-2 space-y-2">
            <div className="h-5" />
            <div className="h-5" />
          </div>
          <div className="mt-auto grid grid-cols-2 gap-2">
            <div className="h-9 rounded-lg" />
            <div className="h-9 rounded-lg" />
          </div>
          <div className="mt-2 flex items-center justify-between">
            <div className="h-3 w-12" />
            <div className="h-3 w-16" />
          </div>
        </div>
      ))}
    </div>
  );
}
