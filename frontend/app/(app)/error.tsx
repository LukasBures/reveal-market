"use client";

export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex flex-1 items-center justify-center bg-gradient-to-b from-slate-950 via-slate-950 to-black px-4 py-24 text-white">
      <div className="max-w-md space-y-6 text-center">
        <h2 className="text-xl font-semibold">Something went wrong</h2>
        <p className="text-sm text-white/60">
          We hit an unexpected error loading this page.
        </p>
        <button
          onClick={reset}
          className="rounded-xl bg-white/10 px-6 py-2 text-sm font-medium transition hover:bg-white/20"
        >
          Try again
        </button>
      </div>
    </div>
  );
}
