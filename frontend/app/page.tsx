export default function HomePage() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-black text-white px-4">
      <h1 className="text-5xl font-semibold text-center">Reveal Market</h1>
      <p className="mt-4 text-lg text-slate-300 text-center max-w-xl">
        Zero-knowledge prediction markets. Launching soon.
      </p>
      <a
        className="mt-6 rounded-full bg-white px-6 py-3 text-black font-semibold transition hover:bg-white/80"
        href="mailto:hello@revealmarket.xyz"
      >
        Contact Us
      </a>
      <a
        className="mt-3 text-sm text-slate-400 underline decoration-dotted"
        href="https://x.com/RevealMarket"
        target="_blank"
        rel="noreferrer"
      >
        Follow updates on X
      </a>
    </div>
  );
}
