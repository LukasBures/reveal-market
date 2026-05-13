"use client";

import { useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";

export const NAVIGATION_FEEDBACK_EVENT = "rm:navigation-start";

const FALLBACK_HIDE_MS = 15_000;

export function notifyNavigationStart() {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new Event(NAVIGATION_FEEDBACK_EVENT));
}

export function NavigationFeedback() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const routeKey = `${pathname ?? ""}?${searchParams?.toString() ?? ""}`;
  const [pending, setPending] = useState(false);

  useEffect(() => {
    const handleStart = () => setPending(true);
    window.addEventListener(NAVIGATION_FEEDBACK_EVENT, handleStart);
    return () => window.removeEventListener(NAVIGATION_FEEDBACK_EVENT, handleStart);
  }, []);

  useEffect(() => {
    setPending(false);
  }, [routeKey]);

  useEffect(() => {
    if (!pending) {
      return;
    }
    const timeout = window.setTimeout(() => setPending(false), FALLBACK_HIDE_MS);
    return () => window.clearTimeout(timeout);
  }, [pending]);

  if (!pending) {
    return null;
  }

  return (
    <div className="pointer-events-none fixed inset-x-0 top-0 z-[90]" role="status" aria-live="polite" aria-label="Opening market">
      <div className="h-1 w-full overflow-hidden bg-white/10">
        <div className="h-full w-1/2 animate-[navigation-progress_1s_ease-in-out_infinite] bg-brand-400 shadow-[0_0_24px_rgba(123,240,94,0.75)]" />
      </div>
      <span className="sr-only">Opening market</span>
    </div>
  );
}
