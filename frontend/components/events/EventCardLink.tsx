"use client";

import type { AnchorHTMLAttributes, MouseEvent, ReactNode } from "react";
import { useCallback, useEffect, useRef } from "react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { notifyNavigationStart } from "@/components/providers/NavigationFeedback";

type EventCardLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: Route;
  children?: ReactNode;
  prefetchOnView?: boolean;
};

export function EventCardLink({
  href,
  children,
  prefetchOnView = false,
  onClick,
  onFocus,
  onMouseEnter,
  onPointerEnter,
  onTouchStart,
  ...props
}: EventCardLinkProps) {
  const router = useRouter();
  const anchorRef = useRef<HTMLAnchorElement | null>(null);
  const prefetchedHrefRef = useRef<string | null>(null);
  const prefetchRoute = useCallback(() => {
    if (typeof href !== "string" || prefetchedHrefRef.current === href) {
      return;
    }
    prefetchedHrefRef.current = href;
    router.prefetch(href);
  }, [href, router]);
  const isModifiedClick = (event: MouseEvent<HTMLAnchorElement>) =>
    event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;

  useEffect(() => {
    if (!prefetchOnView || typeof window === "undefined") {
      return;
    }
    const anchor = anchorRef.current;
    if (!anchor) {
      return;
    }
    if (typeof window.IntersectionObserver === "undefined") {
      const timeout = window.setTimeout(prefetchRoute, 250);
      return () => window.clearTimeout(timeout);
    }
    let timeout: number | null = null;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) {
          return;
        }
        observer.disconnect();
        timeout = window.setTimeout(prefetchRoute, 150);
      },
      { rootMargin: "900px 0px" },
    );
    observer.observe(anchor);
    return () => {
      observer.disconnect();
      if (timeout) {
        window.clearTimeout(timeout);
      }
    };
  }, [prefetchOnView, prefetchRoute]);

  return (
    <Link
      {...props}
      ref={anchorRef}
      href={href}
      prefetch={false}
      onClick={(event) => {
        if (!isModifiedClick(event)) {
          notifyNavigationStart();
        }
        prefetchRoute();
        onClick?.(event);
      }}
      onFocus={(event) => {
        prefetchRoute();
        onFocus?.(event);
      }}
      onMouseEnter={(event) => {
        prefetchRoute();
        onMouseEnter?.(event);
      }}
      onPointerEnter={(event) => {
        prefetchRoute();
        onPointerEnter?.(event);
      }}
      onTouchStart={(event) => {
        prefetchRoute();
        onTouchStart?.(event);
      }}
    >
      {children}
    </Link>
  );
}
