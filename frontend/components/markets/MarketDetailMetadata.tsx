"use client";

import type { MarketDetail } from "@/lib/api-types";
import { formatDateTime } from "@/lib/formatters";
import { getCommitDeadline } from "@/lib/markets";

type Props = {
  market: MarketDetail;
};

type MetadataItem = {
  label: string;
  value?: string | null;
  mono?: boolean;
  copyDisabled?: boolean;
  href?: string | null;
};

export function MarketDetailMetadata({ market }: Props) {
  const explorerBase = (
    process.env.NEXT_PUBLIC_BLOCK_EXPLORER_URL ?? "https://horizen-testnet.explorer.caldera.xyz"
  ).replace(/\/+$/, "");

  const extraData = (market.extraData && typeof market.extraData === "object" ? market.extraData : null) as
    | Record<string, any>
    | null;
  const gamma = extraData?.gamma as Record<string, any> | undefined;
  const sourceSlug =
    typeof gamma?.slug === "string" && gamma.slug.trim()
      ? gamma.slug
      : typeof market.slug === "string"
        ? market.slug
        : undefined;
  const clobPairId =
    typeof gamma?.clobPairId === "string"
      ? gamma.clobPairId
      : typeof gamma?.pairId === "string"
        ? gamma.pairId
        : undefined;
  const tokenIds = Array.isArray(gamma?.clobTokenIds ?? gamma?.tokenIds)
    ? (gamma?.clobTokenIds ?? gamma?.tokenIds).map((value: any) => String(value))
    : undefined;
  const formattedTokens = tokenIds?.length ? tokenIds.join(", ") : undefined;
  const feeLabel =
    typeof market.rakeBps === "number" && Number.isFinite(market.rakeBps)
      ? `${Math.round(market.rakeBps)} bps`
      : undefined;
  const commitDeadline = getCommitDeadline(market);

  const resolution = (market.resolution ?? (market.extraData?.resolution as any)) || null;
  const resolverSource =
    market.resolutionSource ??
    gamma?.resolution_source ??
    gamma?.resolutionSource ??
    extraData?.resolution_source ??
    null;
  const resolverHref = typeof resolverSource === "string" && resolverSource.startsWith("http") ? resolverSource : null;
  const resolverLabel = resolverSource ?? "Not set";
  type ResolutionWinner = { index: number; label?: string | null; payout?: number | null };
  const resolutionWinners: ResolutionWinner[] = Array.isArray(resolution?.winners)
    ? (resolution.winners as ResolutionWinner[])
    : [];
  const explorerHref = (kind: "address" | "tx", value?: string | null) => {
    if (!value) return null;
    const trimmed = value.trim();
    if (!trimmed) return null;
    return kind === "tx" ? `${explorerBase}/tx/${trimmed}` : `${explorerBase}/address/${trimmed}`;
  };

  const copyToClipboard = async (value?: string | null) => {
    if (!value || typeof navigator === "undefined" || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(value);
    } catch (error) {
      console.error("Unable to copy value", error);
    }
  };

  const metadataItems: MetadataItem[] = [
    {
      label: "Resolver",
      value: resolverLabel,
      href: resolverHref,
      copyDisabled: true,
    },
    {
      label: "UMA status",
      value: market.umaStatus ?? "pending",
      copyDisabled: true,
    },
  ];

  if (market.marketAddress) {
    metadataItems.push({
      label: "Market address",
      value: market.marketAddress,
      mono: true,
      href: explorerHref("address", market.marketAddress),
    });
  }

  if (market.factory) {
    metadataItems.push({ label: "Factory address", value: market.factory, mono: true });
  }

  if (feeLabel) {
    metadataItems.push({ label: "Rake (bps)", value: feeLabel });
  }

  if (clobPairId) {
    metadataItems.push({ label: "CLOB pair ID", value: clobPairId, mono: true });
  }

  if (formattedTokens) {
    metadataItems.push({ label: "Token IDs", value: formattedTokens, mono: true });
  }

  metadataItems.push({
    label: "Commit deadline",
    value: commitDeadline ? formatDateTime(commitDeadline) : "TBA",
    copyDisabled: true,
  });

  metadataItems.push({
    label: "Reveal deadline",
    value: market.revealDeadline ? formatDateTime(market.revealDeadline) : "TBA",
    copyDisabled: true,
  });

  const renderItem = (item: MetadataItem) => {
    const content =
      item.href && item.value ? (
        <a
          href={item.href}
          target="_blank"
          rel="noreferrer"
          className={`${item.mono ? "font-mono text-xs" : "text-base font-semibold text-white"} underline underline-offset-4 hover:text-brand-200`}
        >
          {item.value}
        </a>
      ) : (
        <span className={`${item.mono ? "font-mono text-xs" : "text-base font-semibold text-white"}`}>
          {item.value ?? "—"}
        </span>
      );

    return (
      <div key={item.label} className="w-full rounded-2xl border border-white/10 bg-slate-900/60 px-4 py-3 text-sm text-slate-200">
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">{item.label}</p>
        <div className="mt-2 flex items-center gap-2">
          {content}
          {item.value && !item.copyDisabled && (
            <button
              type="button"
              onClick={() => copyToClipboard(item.value)}
              className="text-xs uppercase tracking-[0.2em] text-slate-400 transition hover:text-brand-200"
              aria-label={`Copy ${item.label}`}
            >
              Copy
            </button>
          )}
        </div>
      </div>
    );
  };

  return (
    <section className="rounded-3xl border border-white/10 bg-slate-950/40 p-6 text-sm text-slate-300">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Prediction metadata</p>
          <h2 className="text-2xl font-semibold text-white">Identifiers & provenance</h2>
          <p className="text-slate-400">
            Copyable addresses, upstream slugs, and resolution details so downstream systems can reconcile audits and payouts.
          </p>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4">
        {metadataItems.map((item) => renderItem(item))}
      </div>

      {market.tags && market.tags.length > 0 && (
        <div className="mt-6 space-y-2">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Tags</p>
          <div className="flex flex-wrap gap-2">
            {market.tags.map((tag) => (
              <span key={tag} className="rounded-full bg-brand-500/15 px-3 py-1 text-xs font-semibold text-brand-200">
                #{tag}
              </span>
            ))}
          </div>
        </div>
      )}

      {resolution && (
        <div className="mt-6 space-y-3 rounded-3xl border border-white/10 bg-slate-900/40 p-6">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Resolution</p>
          <div className="text-sm text-slate-300 space-y-2">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-white">{resolution.resolved ? "Resolved" : "Pending"}</span>
              {resolution.checkedAt && (
                <span className="text-xs text-slate-500">{formatDateTime(resolution.checkedAt)}</span>
              )}
            </div>
            {resolutionWinners.length > 0 && (
              <ul className="space-y-1 text-sm">
                {resolutionWinners.map((winner: ResolutionWinner) => (
                  <li key={`${winner.index}-${winner.label ?? winner.index}`}>
                    <span className="font-semibold text-white">{winner.label ?? `Outcome ${winner.index}`}</span>
                    <span className="text-slate-400">
                      {" "}
                      — payout {typeof winner.payout === "number" ? `${Math.round(winner.payout * 100)}%` : "pending"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {(resolution.transactionHash || resolution.blockNumber) && (
              <div className="rounded-2xl border border-white/10 bg-slate-900/70 p-3 text-xs text-slate-400">
                {resolution.transactionHash && (
                  <p className="break-all">
                    TX:{" "}
                    {explorerHref("tx", resolution.transactionHash) ? (
                      <a
                        href={explorerHref("tx", resolution.transactionHash) ?? undefined}
                        target="_blank"
                        rel="noreferrer"
                        className="underline underline-offset-4 hover:text-brand-200"
                      >
                        {resolution.transactionHash}
                      </a>
                    ) : (
                      resolution.transactionHash
                    )}{" "}
                    <button
                      type="button"
                      onClick={() => copyToClipboard(resolution.transactionHash)}
                      className="ml-2 text-[10px] uppercase tracking-[0.2em] text-slate-400 hover:text-brand-200"
                    >
                      Copy
                    </button>
                  </p>
                )}
                {resolution.blockNumber && <p>Block #{resolution.blockNumber}</p>}
              </div>
            )}
          </div>
        </div>
      )}

    </section>
  );
}
