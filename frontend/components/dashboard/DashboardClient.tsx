"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { useAccount, useChainId, usePublicClient, useReadContract, useWriteContract } from "wagmi";
import { useSignMessage } from "wagmi";
import type { Address, Hex } from "viem";
import { bytesToHex, encodePacked, erc20Abi, hexToBytes, keccak256, maxUint256 } from "viem";
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
  const { writeContractAsync } = useWriteContract();
  const publicClient = usePublicClient({ chainId });
  const { signMessageAsync } = useSignMessage();
  const escrowAddress = RELAYER_ESCROW_ADDRESS;
  const tokenAddress = ZEN_TOKEN_ADDRESS;
  const [depositInput, setDepositInput] = useState<string>("0.10");
  const [withdrawInput, setWithdrawInput] = useState<string>("0.00");
  const [escrowStatus, setEscrowStatus] = useState<string | null>(null);
  const [escrowError, setEscrowError] = useState<string | null>(null);
  const { data: onchainEscrowBalance } = useReadContract({
    address: escrowAddress ?? undefined,
    abi: [
      {
        name: "balances",
        type: "function",
        stateMutability: "view",
        inputs: [{ name: "", type: "address" }],
        outputs: [{ name: "", type: "uint256" }],
      },
    ],
    functionName: "balances",
    args: escrowAddress && address ? [address as Address] : undefined,
    query: { enabled: Boolean(escrowAddress && address) },
  });
  const { data: tokenBalance } = useReadContract({
    address: tokenAddress ?? undefined,
    abi: erc20Abi,
    functionName: "balanceOf",
    args: tokenAddress && address ? ([address as Address] as const) : undefined,
    query: { enabled: Boolean(tokenAddress && address) },
  });
  const { data: escrowAllowance } = useReadContract({
    address: tokenAddress ?? undefined,
    abi: erc20Abi,
    functionName: "allowance",
    args:
      tokenAddress && escrowAddress && address
        ? ([address as Address, escrowAddress as Address] as const)
        : undefined,
    query: { enabled: Boolean(tokenAddress && escrowAddress && address), refetchInterval: 15000 },
  });
  const fundingBlockedReason = !escrowAddress || !tokenAddress
    ? "Escrow or token address missing"
    : chainMismatch
      ? `Switch to ${defaultChain.name}`
      : null;

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
        const message = `claim-bundles:${wallet.toLowerCase()}`;
        const signature = await signMessageAsync({ message });
        const res = await fetchClaimBundles(wallet, signature);
        setClaimBundles(res.bundles || []);
        if (res.error) {
          setBundleError(res.error);
        }
      } catch (err) {
        setBundleError(err instanceof Error ? err.message : "Failed to load claim bundles");
      }
    },
    [signMessageAsync],
  );

  const bundleLookup = useMemo(() => {
    const map = new Map<string, ClaimBundle>();
    claimBundles.forEach((bundle) => {
      map.set(`${bundle.marketId}:${bundle.ticketId}`, bundle);
    });
    return map;
  }, [claimBundles]);

  const handleDeposit = async () => {
    setEscrowError(null);
    setEscrowStatus(null);
    if (!address || !escrowAddress || !tokenAddress) {
      setEscrowError("Missing wallet, escrow, or token configuration.");
      return;
    }
    if (chainMismatch) {
      setEscrowError(`Switch to ${defaultChain.name} before funding escrow.`);
      return;
    }
    const amountZen = Number(depositInput.replace(",", "."));
    if (!Number.isFinite(amountZen) || amountZen <= 0) {
      setEscrowError("Enter a deposit amount.");
      return;
    }
    const amountWei = BigInt(Math.floor(amountZen * 1e18));
    try {
      if (!escrowAllowance || escrowAllowance < amountWei) {
        const approveHash = await writeContractAsync({
          address: tokenAddress as Address,
          abi: erc20Abi,
          functionName: "approve",
          args: [escrowAddress as Address, maxUint256],
          chainId,
        });
        setEscrowStatus(`Approve tx: ${approveHash.slice(0, 10)}…${approveHash.slice(-6)}`);
        if (publicClient) {
          await publicClient.waitForTransactionReceipt({ hash: approveHash as any });
        }
      }
      const depositHash = await writeContractAsync({
        address: escrowAddress as Address,
        abi: [
          {
            name: "deposit",
            type: "function",
            stateMutability: "nonpayable",
            inputs: [{ name: "amount", type: "uint256" }],
            outputs: [],
          },
        ],
        functionName: "deposit",
        args: [amountWei],
        chainId,
      });
      setEscrowStatus(`Deposit tx: ${depositHash.slice(0, 10)}…${depositHash.slice(-6)}`);
      if (publicClient) {
        await publicClient.waitForTransactionReceipt({ hash: depositHash as any });
      }
      await load(address);
      await loadBundles(address);
    } catch (err) {
      setEscrowError(err instanceof Error ? err.message : "Deposit failed");
    }
  };

  const handleWithdraw = async () => {
    setEscrowError(null);
    setEscrowStatus(null);
    if (!address || !escrowAddress) {
      setEscrowError("Missing wallet or escrow configuration.");
      return;
    }
    if (chainMismatch) {
      setEscrowError(`Switch to ${defaultChain.name} before withdrawing.`);
      return;
    }
    const amountZen = Number(withdrawInput.replace(",", "."));
    if (!Number.isFinite(amountZen) || amountZen <= 0) {
      setEscrowError("Enter a withdraw amount.");
      return;
    }
    const amountWei = BigInt(Math.floor(amountZen * 1e18));
    if (escrowBalanceBigInt !== null && amountWei > escrowBalanceBigInt) {
      setEscrowError("Withdraw amount exceeds escrow balance.");
      return;
    }
    try {
      const withdrawHash = await writeContractAsync({
        address: escrowAddress as Address,
        abi: [
          {
            name: "withdraw",
            type: "function",
            stateMutability: "nonpayable",
            inputs: [{ name: "amount", type: "uint256" }],
            outputs: [],
          },
        ],
        functionName: "withdraw",
        args: [amountWei],
        chainId,
      });
      setEscrowStatus(`Withdraw tx: ${withdrawHash.slice(0, 10)}…${withdrawHash.slice(-6)}`);
      if (publicClient) {
        await publicClient.waitForTransactionReceipt({ hash: withdrawHash as any });
      }
      await load(address);
      await loadBundles(address);
    } catch (err) {
      setEscrowError(err instanceof Error ? err.message : "Withdraw failed");
    }
  };

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
    if (!bundle.salt) {
      setClaimMessage("Claim data missing salt.");
      return;
    }
    try {
      const userSalt = keccak256(encodePacked(["address", "bytes32"], [bundle.user as Address, bundle.salt as Hex]));
      const leafHex = keccak256(
        encodePacked(
          ["uint256", "uint256", "uint256", "bytes32"],
          [BigInt(bundle.ticketId), BigInt(bundle.outcomeId), BigInt(bundle.amountWei), userSalt as Hex],
        ),
      );
      const storedLeaf = bundle.leaf.startsWith("0x") ? bundle.leaf.toLowerCase() : `0x${bundle.leaf.toLowerCase()}`;
      if (leafHex.toLowerCase() !== storedLeaf) {
        setClaimMessage("Bundle integrity check failed (leaf mismatch).");
        return;
      }
      let computed = hexToBytes(leafHex as Hex);
      let idx = bundle.ticketId;
      for (const sibling of bundle.merkleProof || []) {
        const siblingBytes = hexToBytes(sibling as Hex);
        const combined =
          idx & 1
            ? new Uint8Array([...siblingBytes, ...computed])
            : new Uint8Array([...computed, ...siblingBytes]);
        computed = hexToBytes(keccak256(combined));
        idx = Math.floor(idx / 2);
      }
      const computedRoot = bytesToHex(computed).toLowerCase();
      const providedRoot = (bundle.commitmentsRoot ?? "").toLowerCase();
      const normalizedRoot = providedRoot.startsWith("0x") ? providedRoot : `0x${providedRoot}`;
      if (providedRoot && computedRoot !== normalizedRoot) {
        setClaimMessage("Bundle integrity check failed (root mismatch).");
        return;
      }
    } catch (err) {
      setClaimMessage(err instanceof Error ? `Bundle validation failed: ${err.message}` : "Bundle validation failed");
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
  const escrowBalanceBigInt =
    onchainEscrowBalance !== undefined && onchainEscrowBalance !== null ? BigInt(onchainEscrowBalance) : null;
  const normalizedOnchainEscrow =
    escrowBalanceBigInt !== null ? Number(escrowBalanceBigInt) : null;

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
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <div className="rounded-2xl border border-white/10 bg-gradient-to-br from-emerald-900/40 via-black/60 to-black/80 p-4 shadow-inner shadow-emerald-900/30">
            <div className="flex items-center justify-between text-slate-300">
              <p className="text-xs uppercase tracking-[0.2em] text-emerald-200">Deposit</p>
              <span className="text-[11px] text-slate-400">
                Wallet:{" "}
                {tokenBalance !== undefined && tokenBalance !== null
                  ? `${(Number(tokenBalance) / 1e18).toFixed(3)} ZEN`
                  : "—"}
              </span>
            </div>
            <div className="mt-3 flex items-center gap-3">
              <input
                type="number"
                value={depositInput}
                onChange={(e) => setDepositInput(e.target.value)}
                className="w-full rounded-lg border border-emerald-500/40 bg-slate-900/70 px-3 py-2 text-white shadow-sm shadow-emerald-900/30 focus:border-emerald-300 focus:outline-none"
                step="0.01"
                min="0"
                aria-label="Deposit amount"
              />
              <button
                type="button"
                onClick={handleDeposit}
                className="whitespace-nowrap rounded-full bg-emerald-500 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-white shadow-lg shadow-emerald-900/50 transition hover:-translate-y-[1px] hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-emerald-800/60"
                disabled={Boolean(fundingBlockedReason)}
                title={fundingBlockedReason ?? "Approve and deposit to escrow"}
              >
                Approve &amp; Deposit
              </button>
            </div>
            {fundingBlockedReason && <p className="mt-2 text-xs text-amber-200">{fundingBlockedReason}</p>}
            {escrowStatus && <p className="mt-2 text-xs text-emerald-200">{escrowStatus}</p>}
            {escrowError && <p className="mt-2 text-xs text-rose-300">{escrowError}</p>}
          </div>
          <div className="rounded-2xl border border-white/10 bg-gradient-to-br from-slate-800/40 via-black/60 to-black/80 p-4 shadow-inner shadow-black/40">
            <div className="flex items-center justify-between text-slate-300">
              <p className="text-xs uppercase tracking-[0.2em] text-slate-200">Withdraw</p>
              <span className="text-[11px] text-slate-400">
                Escrow:{" "}
                {normalizedOnchainEscrow !== null && Number.isFinite(normalizedOnchainEscrow)
                  ? `${(normalizedOnchainEscrow / 1e18).toFixed(3)} ZEN`
                  : "—"}
              </span>
            </div>
            <div className="mt-3 flex items-center gap-3">
              <input
                type="number"
                value={withdrawInput}
                onChange={(e) => setWithdrawInput(e.target.value)}
                className="w-full rounded-lg border border-white/20 bg-slate-900/70 px-3 py-2 text-white shadow-sm shadow-black/40 focus:border-white/60 focus:outline-none"
                step="0.01"
                min="0"
                aria-label="Withdraw amount"
              />
              <button
                type="button"
                onClick={handleWithdraw}
                className="whitespace-nowrap rounded-full bg-white/15 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-white shadow-lg shadow-black/50 transition hover:-translate-y-[1px] hover:bg-white/25 disabled:cursor-not-allowed disabled:bg-white/10"
                disabled={
                  chainMismatch ||
                  !RELAYER_ESCROW_ADDRESS ||
                  !ZEN_TOKEN_ADDRESS ||
                  !normalizedOnchainEscrow ||
                  normalizedOnchainEscrow <= 0
                }
                title={chainMismatch ? `Switch to ${defaultChain.name}` : ""}
              >
                Withdraw
              </button>
            </div>
          </div>
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
