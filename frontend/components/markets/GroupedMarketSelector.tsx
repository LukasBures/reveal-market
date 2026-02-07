"use client";

import Link from "next/link";
import type { Route } from "next";
import type { UrlObject } from "url";
import { useMemo, useState } from "react";
import type { MarketSibling } from "@/lib/api-types";
import { formatDate, formatUsd } from "@/lib/formatters";

type Props = {
  groupSlug?: string | null;
  siblings: MarketSibling[];
  activeEventId: string;
  linkToGroupPage?: boolean;
  labelOverride?: string;
  titleOverride?: string;
  subtitleOverride?: string;
  forceShow?: boolean;
  onSelect?: (eventId: string) => void;
};

const formatGroupTitle = (slug?: string | null): string => {
  if (!slug) return "Market";
  return slug
    .split("-")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
};

const formatPrice = (value: number | null | undefined): string => {
  if (typeof value === "number" && Number.isFinite(value)) {
    const pct = value * 100;
    return `${pct.toFixed(2)}%`;
  }
  return "—";
};

export function GroupedMarketSelector({
  groupSlug,
  siblings,
  activeEventId,
  linkToGroupPage = false,
  labelOverride,
  titleOverride,
  subtitleOverride,
  forceShow = false,
  onSelect,
}: Props) {
  const labeledSiblings = useMemo(() => {
    const used = new Set<string>();
    const formatDay = (value?: string | null) => {
      const formatted = value ? formatDate(value, { dateStyle: "medium" }) : "—";
      return formatted !== "—" ? formatted : null;
    };
    const labeled = siblings.map((sibling, index) => {
      const options = [
        sibling.title?.trim(),
        sibling.groupItemTitle?.trim(),
        formatDay(sibling.commitDeadline),
        formatDay(sibling.closesAt),
        formatDay(sibling.startsAt),
        sibling.groupPosition !== null && sibling.groupPosition !== undefined ? `Day ${sibling.groupPosition}` : null,
        sibling.groupItemThreshold !== null && sibling.groupItemThreshold !== undefined
          ? String(sibling.groupItemThreshold)
          : null,
        sibling.title,
        `Market ${index + 1}`,
      ].filter((opt): opt is string => Boolean(opt));

      let label = options.find((opt) => !used.has(opt)) ?? options[0] ?? `Market ${index + 1}`;
      if (used.has(label)) {
        label = `${label} #${index + 1}`;
      }
      used.add(label);

      return { ...sibling, _label: label };
    });
    const parseDate = (value?: string | null) => {
      if (!value) return null;
      const ts = Date.parse(value);
      return Number.isNaN(ts) ? null : ts;
    };
    const score = (sibling: MarketSibling & { _label?: string }) => {
      if (typeof sibling.groupPosition === "number" && Number.isFinite(sibling.groupPosition)) {
        return { rank: 0, value: sibling.groupPosition };
      }
      if (typeof sibling.groupItemThreshold === "number" && Number.isFinite(sibling.groupItemThreshold)) {
        return { rank: 1, value: sibling.groupItemThreshold };
      }
      const dates = [sibling.commitDeadline, sibling.closesAt, sibling.startsAt]
        .map((d) => parseDate(d))
        .filter((d): d is number => d !== null);
      if (dates.length) {
        return { rank: 2, value: Math.min(...dates) };
      }
      const label = sibling._label ?? "";
      return { rank: 3, value: label.toLowerCase() };
    };
    return labeled.sort((a, b) => {
      const sa = score(a as MarketSibling & { _label?: string });
      const sb = score(b as MarketSibling & { _label?: string });
      if (sa.rank !== sb.rank) return sa.rank - sb.rank;
      if (typeof sa.value === "number" && typeof sb.value === "number") return sa.value - sb.value;
      return String(sa.value).localeCompare(String(sb.value));
    });
  }, [siblings]);

  const now = Date.now();
  const isEnded = useMemo(() => {
    return (sibling: MarketSibling) => {
      const status = (sibling.status ?? "").toLowerCase();
      if (["settled", "resolved", "cancelled", "canceled", "voided", "closed"].includes(status)) {
        return true;
      }
      const candidates = [sibling.commitDeadline, sibling.closesAt]
        .map((value) => (value ? Date.parse(value) : NaN))
        .filter((value) => Number.isFinite(value));
      if (!candidates.length) return false;
      return Math.min(...candidates) < now;
    };
  }, [now]);

  const activeEnded = useMemo(
    () => labeledSiblings.some((sibling) => sibling.eventId === activeEventId && isEnded(sibling)),
    [activeEventId, labeledSiblings, isEnded],
  );
  const [showEnded, setShowEnded] = useState(activeEnded);

  const { activeSiblings, endedSiblings } = useMemo(() => {
    const active: (MarketSibling & { _label?: string })[] = [];
    const ended: (MarketSibling & { _label?: string })[] = [];
    labeledSiblings.forEach((sibling) => {
      if (isEnded(sibling)) {
        ended.push(sibling);
      } else {
        active.push(sibling);
      }
    });
    return { activeSiblings: active, endedSiblings: ended };
  }, [labeledSiblings, isEnded]);

  const shouldShow = forceShow || (!!groupSlug && siblings.length > 1);
  if (!shouldShow) return null;

  const title = titleOverride ?? formatGroupTitle(groupSlug);
  const label = labelOverride ?? "Grouped market";
  const subtitle = subtitleOverride ?? "Select a threshold to jump between sub-markets.";
  const countLabel = endedSiblings.length
    ? `${activeSiblings.length} active · ${endedSiblings.length} ended`
    : `${siblings.length} sub-market${siblings.length === 1 ? "" : "s"}`;

  return (
    <section className="rounded-3xl border border-white/10 bg-slate-950/40 px-5 py-5 shadow-inner shadow-emerald-500/10 sm:px-7 sm:py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-[0.3em] text-emerald-200/70">{label}</p>
          <h2 className="text-xl font-semibold text-white">{title}</h2>
          <p className="text-sm text-emerald-100/80">{subtitle}</p>
        </div>
        <span className="rounded-full border border-emerald-700 bg-emerald-500/20 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.25em] text-emerald-50">
          {countLabel}
        </span>
      </div>
      <div className="mt-4 space-y-2">
        {activeSiblings.map((sibling) => {
          const yesPrice = formatPrice(sibling.outcomePrices?.[0] ?? null);
          const noPrice = formatPrice(sibling.outcomePrices?.[1] ?? null);
          const volume = sibling.volume ?? 0;
          const active = sibling.eventId === activeEventId;
          const label = (sibling as MarketSibling & { _label?: string })._label ?? "Sub-market";
          const href: UrlObject | Route =
            linkToGroupPage && groupSlug
              ? { pathname: `/events/${encodeURIComponent(groupSlug)}`, query: { eventId: sibling.eventId } }
              : (`/events/${encodeURIComponent(sibling.eventId)}` as Route);
          const className = `flex w-full min-h-[112px] flex-wrap items-center justify-between gap-3 rounded-2xl border px-4 py-3 transition sm:grid sm:grid-cols-[1.2fr,0.9fr,0.9fr,1fr] sm:items-center ${
            active
              ? "border-emerald-400 bg-emerald-500/10 shadow-md shadow-emerald-500/20"
              : "border-white/5 bg-white/5 hover:border-emerald-400/60 hover:bg-white/10"
          }`;
          if (onSelect) {
            return (
              <button
                key={`${sibling.eventId}-summary`}
                type="button"
                onClick={() => onSelect(sibling.eventId)}
                className={className}
              >
                <span className="text-[11px] uppercase tracking-[0.25em] text-white/80">{label}</span>
                <span className="text-sm text-white sm:text-right">Yes {yesPrice}</span>
                <span className="text-sm text-white sm:text-right">No {noPrice}</span>
                <span className="text-xs text-slate-200 sm:text-right">Volume {formatUsd(volume)}</span>
              </button>
            );
          }
          return (
            <Link key={`${sibling.eventId}-summary`} href={href} scroll={false} className={className}>
              <span className="text-[11px] uppercase tracking-[0.25em] text-white/80">{label}</span>
              <span className="text-sm text-white sm:text-right">Yes {yesPrice}</span>
              <span className="text-sm text-white sm:text-right">No {noPrice}</span>
              <span className="text-xs text-slate-200 sm:text-right">Volume {formatUsd(volume)}</span>
            </Link>
          );
        })}
        {endedSiblings.length > 0 ? (
          <div className="pt-2">
            <button
              type="button"
              onClick={() => setShowEnded((prev) => !prev)}
              className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-xs font-semibold uppercase tracking-[0.25em] text-white/80 transition hover:border-emerald-400/60 hover:text-white"
              aria-expanded={showEnded}
            >
              {showEnded ? "Hide ended markets" : "Show ended markets"}
              <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-white/70">
                {endedSiblings.length}
              </span>
            </button>
          </div>
        ) : null}
        {showEnded
          ? endedSiblings.map((sibling) => {
              const yesPrice = formatPrice(sibling.outcomePrices?.[0] ?? null);
              const noPrice = formatPrice(sibling.outcomePrices?.[1] ?? null);
              const volume = sibling.volume ?? 0;
              const active = sibling.eventId === activeEventId;
              const label = (sibling as MarketSibling & { _label?: string })._label ?? "Sub-market";
              const href: UrlObject | Route =
                linkToGroupPage && groupSlug
                  ? { pathname: `/events/${encodeURIComponent(groupSlug)}`, query: { eventId: sibling.eventId } }
                  : (`/events/${encodeURIComponent(sibling.eventId)}` as Route);
              const className = `flex w-full min-h-[112px] flex-wrap items-center justify-between gap-3 rounded-2xl border px-4 py-3 transition sm:grid sm:grid-cols-[1.2fr,0.9fr,0.9fr,1fr] sm:items-center ${
                active
                  ? "border-amber-400 bg-amber-500/10 shadow-md shadow-amber-500/20"
                  : "border-white/5 bg-white/5 hover:border-emerald-400/60 hover:bg-white/10"
              }`;
              if (onSelect) {
                return (
                  <button
                    key={`${sibling.eventId}-ended`}
                    type="button"
                    onClick={() => onSelect(sibling.eventId)}
                    className={className}
                  >
                    <span className="text-[11px] uppercase tracking-[0.25em] text-white/80">{label}</span>
                    <span className="text-sm text-white sm:text-right">Yes {yesPrice}</span>
                    <span className="text-sm text-white sm:text-right">No {noPrice}</span>
                    <span className="text-xs text-slate-200 sm:text-right">Volume {formatUsd(volume)}</span>
                  </button>
                );
              }
              return (
                <Link key={`${sibling.eventId}-ended`} href={href} scroll={false} className={className}>
                  <span className="text-[11px] uppercase tracking-[0.25em] text-white/80">{label}</span>
                  <span className="text-sm text-white sm:text-right">Yes {yesPrice}</span>
                  <span className="text-sm text-white sm:text-right">No {noPrice}</span>
                  <span className="text-xs text-slate-200 sm:text-right">Volume {formatUsd(volume)}</span>
                </Link>
              );
            })
          : null}
      </div>
    </section>
  );
}
