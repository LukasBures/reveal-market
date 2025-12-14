"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { useAccount, useChainId } from "wagmi";
import type { Address, Hex } from "viem";
import { fetchPositions, fetchClaimBundles } from "@/lib/api";
import type { ClaimBundle, PositionRecord } from "@/lib/api-types";
import { defaultChain } from "@/lib/wagmi";
import { RELAYER_ESCROW_ADDRESS, ZEN_TOKEN_ADDRESS } from "@/lib/tokens";
import { formatDateTime } from "@/lib/formatters";
import Link from "next/link";
import { useClaimTicket } from "@/lib/marketContract";

export function DashboardClient() {
  const { address, isConnected } = useAccount();
  const chainId = useChainId();
  const chainMismatch = Boolean(chainId && chainId !== defaultChain.id);
  const [positions, setPositions] = useState<PositionRecord[]>([]);
  const [loading, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [escrowBalance, setEscrowBalance] = useState<string | number | null>(null);
  const [claimingTicket, setClaimingTicket] = useState<string | null>(null);
  const [claimMessage, setClaimMessage] = useState<string | null>(null);
  const [claimBundles, setClaimBundles] = useState<ClaimBundle[]>([]);
  const [bundleError, setBundleError] = useState<string | null>(null);
  const { claimTicket, isPending: claimPending, error: claimError } = useClaimTicket();

  const load = useMemo(
    () => async (wallet: string) => {
      try {
        setError(null);
        const res = await fetchPositions(wallet);
        setPositions(res.positions || []);
        setEscrowBalance(res.escrowBalance ?? null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load positions");
      }
    },
    [],
  );

  const loadBundles = useMemo(
    () => async (wallet: string) => {
      try {
        setBundleError(null);
        const res = await fetchClaimBundles(wallet);
        setClaimBundles(res.bundles || []);
        if (res.error) {
          setBundleError(res.error);
        }
      } catch (err) {
        setBundleError(err instanceof Error ? err.message : "Failed to load claim bundles");
      }
    },
    [],
  );

  const bundleLookup = useMemo(() => {
    const map = new Map<string, ClaimBundle>();
    claimBundles.forEach((bundle) => {
      map.set(`${bundle.marketId}:${bundle.ticketId}`, bundle);
    });
    return map;
  }, [claimBundles]);

  useEffect(() => {
    if (!address) {
      setPositions([]);
      setClaimBundles([]);
      return;
    }
    startTransition(() => {
      void load(address);
      void loadBundles(address);
    });
  }, [address, load, loadBundles]);

  const handleClaim = async (marketId: string, ticketId?: number | null) => {
    if (!address) return;
    const key = `${marketId}:${ticketId ?? "na"}`;
    const bundle = bundleLookup.get(key);
    if (!bundle) {
      setClaimMessage("Claim data not available yet.");
      return;
    }
    if (!bundle.marketAddress) {
      setClaimMessage("Market address missing for claim.");
      return;
    }
    setClaimingTicket(key);
    setClaimMessage(null);
    try {
      const txHash = await claimTicket({
        marketAddress: bundle.marketAddress as Address,
        user: bundle.user as Address,
        ticketId: BigInt(bundle.ticketId),
        outcomeId: BigInt(bundle.outcomeId),
        amountWei: BigInt(bundle.amountWei),
        salt: (bundle.salt ?? "0x") as Hex,
        merkleProof: (bundle.merkleProof ?? []) as Hex[],
      });
      setClaimMessage(`Claim sent: ${txHash}`);
      await load(address);
      await loadBundles(address);
    } catch (err) {
      setClaimMessage(err instanceof Error ? err.message : "Claim failed");
    } finally {
      setClaimingTicket(null);
    }
  };

  if (!isConnected || !address) {
    return (
      <div className="rounded-3xl border border-white/10 bg-white/5 p-6 text-center text-slate-300">
        Connect your wallet to view positions.
      </div>
    );
  }

  const normalizedEscrow = escrowBalance !== null ? Number(escrowBalance) : null;
  const escrowDisplay =
    normalizedEscrow !== null && Number.isFinite(normalizedEscrow) ? (normalizedEscrow / 1e18).toFixed(3) : "—";

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-white/10 bg-slate-950/60 p-4">
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Escrow</p>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-white">
          <span>Balance: {escrowDisplay} ZEN {ZEN_TOKEN_ADDRESS ? "" : "(ZEN token missing)"}</span>
          <span className="text-slate-400">
            Escrow: {RELAYER_ESCROW_ADDRESS ?? "n/a"} | Chain: {chainMismatch ? "Wrong network" : defaultChain.name}
          </span>
        </div>
      </div>
      {error ? (
        <div className="rounded-3xl border border-rose-400/30 bg-rose-500/10 p-6 text-rose-100">
          {error}
        </div>
      ) : loading ? (
        <div className="rounded-3xl border border-white/10 bg-slate-950/60 p-6 text-slate-200">Loading positions…</div>
      ) : positions.length === 0 ? (
        <div className="rounded-3xl border border-white/10 bg-slate-950/60 p-6 text-slate-200">No positions yet.</div>
      ) : (
        <div className="space-y-4">
          {bundleError && (
            <div className="rounded-2xl border border-amber-400/40 bg-amber-500/10 p-3 text-amber-100">
              {bundleError}
            </div>
          )}
          {positions.map((p, idx) => (
            <div
              key={`${p.market_id}-${p.ticket_id ?? idx}`}
              className="rounded-2xl border border-white/10 bg-black/40 p-4 shadow-lg shadow-black/30"
            >
              {(() => {
                const bundleKey = `${p.market_id}:${p.ticket_id ?? "na"}`;
                const bundle = bundleLookup.get(bundleKey);
                return (
                  <>
                    <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-white">
                      <div>
                        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Market</p>
                        <p className="font-semibold">{p.market_title ?? p.market_id}</p>
                        <p className="text-xs text-slate-400">Outcome: {p.outcome_id}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Stake</p>
                        <p className="font-mono text-white">{p.stake_zen.toFixed(3)} ZEN</p>
                      </div>
                      <div className="text-right">
                        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Status</p>
                        <p className={`font-semibold ${p.claimable ? "text-emerald-200" : "text-white"}`}>
                          {p.status}
                          {p.claimable ? " · claimable" : ""}
                        </p>
                      </div>
                    </div>
                    <div className="mt-3 grid gap-2 text-xs text-slate-300 md:grid-cols-4">
                      <span>Ticket: {p.ticket_id ?? "—"}</span>
                      <span>Created: {formatDateTime(p.created_at ?? undefined)}</span>
                      <span>Closes: {formatDateTime(p.closes_at ?? p.resolved_at ?? undefined)}</span>
                      <span>
                        Merkle root: {p.merkle_root ? `${p.merkle_root.slice(0, 8)}…${p.merkle_root.slice(-6)}` : "—"}
                      </span>
                      <span>Quote: {p.quote_id ?? "—"}</span>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-200">
                      {p.status === "settled" && p.claimable ? (
                        <button
                          type="button"
                          className="rounded-full bg-emerald-500 px-3 py-1 font-semibold text-white hover:bg-emerald-400 disabled:cursor-not-allowed"
                          disabled={!bundle || Boolean(claimingTicket) || claimPending || chainMismatch}
                          onClick={() => handleClaim(p.market_id, p.ticket_id)}
                        >
                          {claimingTicket === bundleKey || claimPending ? "Claiming…" : "Claim"}
                        </button>
                      ) : null}
                      {!bundle && p.claimable ? (
                        <span className="text-amber-300">Claim data not available yet.</span>
                      ) : null}
                      <Link
                        className="rounded-full bg-white/10 px-3 py-1 text-white hover:bg-white/20"
                        href={`/markets/${encodeURIComponent(p.market_id)}`}
                      >
                        View market
                      </Link>
                      <Link
                        className="rounded-full bg-white/10 px-3 py-1 text-white hover:bg-white/20"
                        href={
                          p.merkle_root || p.proof_request_id
                            ? `/proofs?eventId=${encodeURIComponent(p.market_id)}`
                            : "/proofs"
                        }
                      >
                        View proofs
                      </Link>
                    </div>
                  </>
                );
              })()}
            </div>
          ))}
          {claimMessage && <p className="text-sm text-emerald-200">{claimMessage}</p>}
          {claimError && (
            <p className="text-sm text-rose-200">
              {claimError instanceof Error ? claimError.message : String(claimError)}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
