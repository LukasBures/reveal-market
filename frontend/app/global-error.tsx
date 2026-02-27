"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body className="flex min-h-screen items-center justify-center bg-slate-950 text-white">
        <div className="mx-auto max-w-md space-y-6 px-4 text-center">
          <h1 className="text-2xl font-semibold">Something went wrong</h1>
          <p className="text-sm text-white/60">
            An unexpected error occurred. Please try again.
          </p>
          <button
            onClick={reset}
            className="rounded-xl bg-white/10 px-6 py-2 text-sm font-medium transition hover:bg-white/20"
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
