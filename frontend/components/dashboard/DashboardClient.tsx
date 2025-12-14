"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { useAccount, useChainId } from "wagmi";
import { fetchPositions } from "@/lib/api";
import type { PositionRecord } from "@/lib/api-types";
import { defaultChain } from "@/lib/wagmi";
import { RELAYER_ESCROW_ADDRESS, ZEN_TOKEN_ADDRESS } from "@/lib/tokens";
import { formatDateTime } from "@/lib/formatters";
import Link from "next/link";
import { submitClaim } from "@/lib/trade-client";

export function DashboardClient() {
  const { address, isConnected } = useAccount();
  const chainId = useChainId();
  const chainMismatch = Boolean(chainId && chainId !== defaultChain.id);
  const [positions, setPositions] = useState<PositionRecord[]>([]);
  const [loading, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [escrowBalance, setEscrowBalance] = useState<string | number | null>(null);
  const [claimingTicket, setClaimingTicket] = useState<number | null>(null);
  const [claimMessage, setClaimMessage] = useState<string | null>(null);

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

  useEffect(() => {
    if (!address) return;
    startTransition(() => {
      void load(address);
    });
  }, [address, load]);

  const handleClaim = async (marketId: string, ticketId?: number | null) => {
    if (!address) return;
    setClaimingTicket(ticketId ?? null);
    setClaimMessage(null);
    try {
      const resp = await submitClaim(marketId, address, ticketId);
      setClaimMessage(`Claim submitted: ${resp.tx_hash ?? resp.status}`);
      await load(address);
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
          {positions.map((p, idx) => (
            <div
              key={`${p.market_id}-${p.ticket_id ?? idx}`}
              className="rounded-2xl border border-white/10 bg-black/40 p-4 shadow-lg shadow-black/30"
            >
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
                    disabled={Boolean(claimingTicket)}
                    onClick={() => handleClaim(p.market_id, p.ticket_id)}
                  >
                    {claimingTicket ? "Claiming…" : "Claim"}
                  </button>
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
            </div>
          ))}
          {claimMessage && <p className="text-sm text-emerald-200">{claimMessage}</p>}
        </div>
      )}
    </div>
  );
}
