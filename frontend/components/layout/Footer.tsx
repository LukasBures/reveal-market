import Link from "next/link";

export function Footer() {
  return (
    <footer className="border-t border-white/10 bg-slate-950/80">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-8 text-sm text-slate-400 md:flex-row md:items-center md:justify-between">
        <p>© {new Date().getFullYear()} Reveal Market. All rights reserved.</p>
        <div className="flex flex-wrap items-center gap-4">
          <Link href="/about" className="hover:text-white">
            About
          </Link>
          <Link href="https://docs.revealmarket.xyz" className="hover:text-white">
            Docs
          </Link>
          <Link href="mailto:hello@revealmarket.xyz" className="hover:text-white">
            Contact
          </Link>
        </div>
      </div>
    </footer>
  );
}
