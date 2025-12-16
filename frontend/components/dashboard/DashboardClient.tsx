"use client";

import { useCallback, useEffect, useMemo, useState, useTransition } from "react";
import { useAccount, useChainId, usePublicClient, useReadContract, useWriteContract } from "wagmi";
import { useSignMessage } from "wagmi";
import type { Address, Hex } from "viem";
import { bytesToHex, encodePacked, erc20Abi, hexToBytes, keccak256, maxUint256 } from "viem";
import { fetchPositions, fetchClaimBundles, fetchMarketByEventId } from "@/lib/api";
import type { ClaimBundle, MarketDetail, PositionRecord } from "@/lib/api-types";
import { defaultChain } from "@/lib/wagmi";
import { RELAYER_ESCROW_ADDRESS, ZEN_TOKEN_ADDRESS } from "@/lib/tokens";
import { formatDateTime } from "@/lib/formatters";
import Link from "next/link";
import { useClaimTicket } from "@/lib/marketContract";
import clsx from "clsx";

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
  const [bundlesRequested, setBundlesRequested] = useState(false);
  const [bundlesLoading, setBundlesLoading] = useState(false);
  const [bundleSignature, setBundleSignature] = useState<string | null>(null);
  const [marketDetails, setMarketDetails] = useState<Map<string, MarketDetail>>(new Map());
  const [statusFilter, setStatusFilter] = useState<"all" | "open" | "settled" | "claimable">("all");
  const [sortBy, setSortBy] = useState<"recent" | "stake" | "closes">("recent");
  const [searchQuery, setSearchQuery] = useState("");
  const { claimTicket, isPending: claimPending, error: claimError } = useClaimTicket();
  const { writeContractAsync } = useWriteContract();
  const publicClient = usePublicClient({ chainId });
  const { signMessageAsync } = useSignMessage();
  const explorerBase = (process.env.NEXT_PUBLIC_EXPLORER_BASE_URL ?? "").replace(/\/+$/, "");
  const escrowAddress = RELAYER_ESCROW_ADDRESS;
  const tokenAddress = ZEN_TOKEN_ADDRESS;
  const [depositInput, setDepositInput] = useState<string>("0.10");
  const [withdrawInput, setWithdrawInput] = useState<string>("0.00");
  const [escrowStatus, setEscrowStatus] = useState<string | null>(null);
  const [escrowError, setEscrowError] = useState<string | null>(null);
  const { data: onchainEscrowBalance, refetch: refetchOnchainEscrow } = useReadContract({
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
  const { data: tokenBalance, refetch: refetchTokenBalance } = useReadContract({
    address: tokenAddress ?? undefined,
    abi: erc20Abi,
    functionName: "balanceOf",
    args: tokenAddress && address ? ([address as Address] as const) : undefined,
    query: { enabled: Boolean(tokenAddress && address) },
  });
  const { data: escrowAllowance, refetch: refetchEscrowAllowance } = useReadContract({
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
  const hasEscrowAllowance = escrowAllowance !== undefined && escrowAllowance !== null && escrowAllowance > 0n;
  const depositCtaLabel = hasEscrowAllowance ? "Deposit" : "Approve & Deposit";
  const depositCtaTitle = fundingBlockedReason
    ? fundingBlockedReason
    : hasEscrowAllowance
      ? "Deposit to escrow"
      : "Approve and deposit to escrow";
  const triggerBundleLoad = () => {
    if (!address) return;
    setBundlesRequested(true);
    void fetchBundlesWithUi(address);
  };

  const sanitizeError = (err: unknown): string => {
    const raw = err instanceof Error ? err.message : String(err);
    const [message] = raw.split("Version:");
    return message.trim() || "Transaction failed";
  };
  const sanitizeUserActionError = useCallback((err: unknown): string => {
    const raw = err instanceof Error ? err.message : String(err);
    const [message] = raw.split("Version:");
    const cleaned = message.replace(/^Details:\s*/i, "").trim();
    return cleaned || "Action cancelled";
  }, []);

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
        setClaimMessage(null);
        const message = `claim-bundles:${wallet.toLowerCase()}`;
        const signature =
          bundleSignature && bundleSignature.length > 0
            ? bundleSignature
            : await signMessageAsync({ message });
        if (!bundleSignature) {
          setBundleSignature(signature);
        }
        const res = await fetchClaimBundles(wallet, signature);
        const bundles = res.bundles || [];
        setClaimBundles(bundles);
        if (res.error) {
          setBundleError(sanitizeUserActionError(res.error));
        }
        if (!res.error && bundles.length === 0) {
          setClaimMessage("No new payouts to load yet. Check again after markets settle.");
        }
        return bundles;
      } catch (err) {
        setBundleError(sanitizeUserActionError(err) || "Failed to load claim bundles");
        return [];
      }
    },
    [bundleSignature, sanitizeUserActionError, signMessageAsync],
  );

  const fetchBundlesWithUi = useMemo(
    () => async (wallet: string) => {
      setBundlesLoading(true);
      try {
        return await loadBundles(wallet);
      } finally {
        setBundlesLoading(false);
      }
    },
    [loadBundles],
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
      await refetchTokenBalance();
      await refetchEscrowAllowance();
      await refetchOnchainEscrow();
      await load(address);
      if (bundlesRequested) {
        await fetchBundlesWithUi(address);
      }
    } catch (err) {
      setEscrowError(sanitizeError(err));
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
      await refetchTokenBalance();
      await refetchEscrowAllowance();
      await refetchOnchainEscrow();
      await load(address);
      if (bundlesRequested) {
        await fetchBundlesWithUi(address);
      }
    } catch (err) {
      setEscrowError(sanitizeError(err));
    }
  };

  useEffect(() => {
    if (!address) {
      setPositions([]);
      setClaimBundles([]);
      setBundleSignature(null);
      setBundlesRequested(false);
      setMarketDetails(new Map());
      return;
    }
    startTransition(() => {
      void load(address);
    });
  }, [address, load]);

  useEffect(() => {
    if (!positions.length) return;
    const knownIds = new Set(marketDetails.keys());
    const missing = positions
      .map((p) => p.market_id)
      .filter((id) => id && !knownIds.has(id));
    if (missing.length === 0) return;
    let cancelled = false;
    (async () => {
      const fetched = await Promise.all(
        missing.map(async (id) => {
          try {
            const detail = await fetchMarketByEventId(id);
            return [id, detail] as const;
          } catch {
            return [id, null] as const;
          }
        }),
      );
      if (cancelled) return;
      setMarketDetails((prev) => {
        const next = new Map(prev);
        fetched.forEach(([id, detail]) => {
          if (detail) next.set(id, detail);
        });
        return next;
      });
    })();
    return () => {
      cancelled = true;
    };
  }, [positions, marketDetails]);

  const handleClaim = async (marketId: string, ticketId?: number | null) => {
    if (!address) return;
    const key = `${marketId}:${ticketId ?? "na"}`;
    let bundle = bundleLookup.get(key);
    if (!bundle) {
      setClaimMessage("Loading claim data for this ticket…");
      setBundlesRequested(true);
      const bundles = await fetchBundlesWithUi(address);
      bundle = bundles.find((b) => `${b.marketId}:${b.ticketId}` === key);
    }
    if (!bundle) {
      setClaimMessage("Claim data not available yet. Click “Load payout data” first.");
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
      await fetchBundlesWithUi(address);
    } catch (err) {
      setClaimMessage(err instanceof Error ? err.message : "Claim failed");
    } finally {
      setClaimingTicket(null);
    }
  };

  const normalizedEscrow = escrowBalance !== null ? Number(escrowBalance) : null;
  const escrowDisplay =
    normalizedEscrow !== null && Number.isFinite(normalizedEscrow) ? (normalizedEscrow / 1e18).toFixed(3) : "—";
  const escrowBalanceBigInt =
    onchainEscrowBalance !== undefined && onchainEscrowBalance !== null ? BigInt(onchainEscrowBalance) : null;
  const normalizedOnchainEscrow =
    escrowBalanceBigInt !== null ? Number(escrowBalanceBigInt) : null;
  const normalizeWei = useCallback((value: unknown): bigint | null => {
    if (value === undefined || value === null) return null;
    try {
      if (typeof value === "bigint") return value;
      if (typeof value === "number" && Number.isFinite(value)) return BigInt(Math.floor(value));
      const asString = String(value);
      if (!asString) return null;
      return BigInt(asString);
    } catch {
      return null;
    }
  }, []);
  const derivedPositions = useMemo(
    () =>
      positions.map((p, idx) => {
        const bundleKey = `${p.market_id}:${p.ticket_id ?? "na"}`;
        const bundle = bundleLookup.get(bundleKey);
        const outcomeLabel =
          p.outcome_label ??
          marketDetails.get(p.market_id)?.outcomes?.[p.outcome_id] ??
          `Outcome ${p.outcome_id}`;
        const potentialZen =
          typeof p.potential_payout_zen === "number" && Number.isFinite(p.potential_payout_zen)
            ? p.potential_payout_zen
            : null;
        const potentialWeiFromPosition = normalizeWei((p as any).potential_payout_wei);
        const toWinWei =
          (bundle && normalizeWei(bundle.amountWei)) ||
          potentialWeiFromPosition ||
          (potentialZen !== null ? normalizeWei(Math.round(potentialZen * 1e18)) : null);
        const market = marketDetails.get(p.market_id);
        const price = market && Array.isArray(market.outcomePrices) ? market.outcomePrices[p.outcome_id] : null;
        const toWinZen =
          toWinWei !== null ? Number(toWinWei) / 1e18 : price && Number.isFinite(price) && price > 0 ? p.stake_zen / price : null;
        const quoteId = p.quote_id ?? (p as any).quoteId ?? (bundle as any)?.quoteId ?? null;
        return { position: p, bundle, bundleKey, outcomeLabel, toWinZen, quoteId, idx };
      }),
    [bundleLookup, marketDetails, normalizeWei, positions],
  );
  const filteredPositions = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return derivedPositions
      .filter(({ position }) => {
        // Hide positions that never produced an on-chain transaction to reduce noise.
        if (!position.tx_hash) return false;
        if (statusFilter === "open" && position.status === "settled") return false;
        if (statusFilter === "settled" && position.status !== "settled") return false;
        if (statusFilter === "claimable" && !position.claimable) return false;
        if (query.length === 0) return true;
        return (position.market_title ?? position.market_id).toLowerCase().includes(query);
      })
      .sort((a, b) => {
        if (sortBy === "stake") {
          return (b.position.stake_zen || 0) - (a.position.stake_zen || 0);
        }
        if (sortBy === "closes") {
          const aClose = a.position.closes_at ? Date.parse(a.position.closes_at) : 0;
          const bClose = b.position.closes_at ? Date.parse(b.position.closes_at) : 0;
          return bClose - aClose;
        }
        const aCreated = a.position.created_at ? Date.parse(a.position.created_at) : 0;
        const bCreated = b.position.created_at ? Date.parse(b.position.created_at) : 0;
        return bCreated - aCreated;
      });
  }, [derivedPositions, searchQuery, sortBy, statusFilter]);
  const totalStakeZen = filteredPositions.reduce(
    (acc, { position }) => acc + (Number.isFinite(position.stake_zen) ? position.stake_zen : 0),
    0,
  );
  const totalToWinZen = filteredPositions.reduce(
    (acc, { toWinZen }) => acc + (toWinZen !== null && Number.isFinite(toWinZen) ? toWinZen : 0),
    0,
  );
  const totalEscrowZen =
    normalizedEscrow !== null && Number.isFinite(normalizedEscrow)
      ? normalizedEscrow / 1e18
      : normalizedOnchainEscrow !== null && Number.isFinite(normalizedOnchainEscrow)
        ? normalizedOnchainEscrow / 1e18
        : null;
  const pnlZen = totalToWinZen - totalStakeZen;
  const roi = totalStakeZen > 0 ? pnlZen / totalStakeZen : null;

  if (!isConnected || !address) {
    return (
      <div className="rounded-3xl border border-white/10 bg-white/5 p-6 text-center text-slate-300">
        Connect your wallet to view positions.
      </div>
    );
  }

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
                title={depositCtaTitle}
              >
                {depositCtaLabel}
              </button>
            </div>
            <p className="mt-1 text-[11px] text-emerald-100/80">
              MetaMask may show an approval first (lets the escrow spend your ZEN), then the actual deposit. You will only
              see the approval once unless you lower your allowance.
            </p>
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
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-rose-400/50 bg-slate-900/50 px-4 py-3 shadow-[0_0_0_1px_rgba(248,113,113,0.35)]">
            <div className="text-xs text-slate-300">
              <p className="font-semibold text-white">Claim data</p>
              <p className="text-slate-400">
              Loading claim bundles requires a one-time wallet signature (no gas). Use it before claiming to avoid
              unexpected pop-ups.
            </p>
          </div>
          <button
            type="button"
            onClick={triggerBundleLoad}
            disabled={bundlesLoading || !address}
            className="rounded-full bg-white/15 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-white shadow-lg shadow-black/50 transition hover:-translate-y-[1px] hover:bg-white/25 disabled:cursor-not-allowed disabled:bg-white/10"
          >
              {bundlesLoading ? "Loading…" : bundlesRequested ? "Refresh payout data" : "Load payout data"}
          </button>
        </div>
          {bundleError && (
            <div className="rounded-2xl border border-amber-400/40 bg-amber-500/10 p-3 text-amber-100">
              {bundleError}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-white/10 bg-gradient-to-r from-slate-900/70 via-slate-900/40 to-slate-800/40 px-4 py-3 shadow-inner shadow-black/30">
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search markets"
              className="min-w-[200px] flex-1 rounded-lg border border-white/20 bg-black/30 px-3 py-2 text-sm text-white shadow-inner shadow-black/40 focus:border-white/60 focus:outline-none"
            />
            <div className="flex flex-wrap items-center gap-2">
              {(["all", "open", "settled", "claimable"] as const).map((filter) => (
                <button
                  key={filter}
                  type="button"
                  onClick={() => setStatusFilter(filter)}
                  className={clsx(
                    "rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide transition",
                    statusFilter === filter
                      ? "bg-white/80 text-black shadow"
                      : "bg-white/10 text-white hover:bg-white/20",
                  )}
                >
                  {filter}
                </button>
              ))}
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-300">
              Sort
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
                className="rounded-lg border border-white/30 bg-black/40 px-2 py-1 text-xs text-white shadow-inner shadow-black/40 focus:border-white/60 focus:outline-none"
              >
                <option value="recent">Most recent</option>
                <option value="stake">Stake size</option>
                <option value="closes">Closing time</option>
              </select>
            </label>
          </div>
          <div className="grid gap-3 rounded-2xl border border-white/10 bg-gradient-to-r from-indigo-900/30 via-slate-900/60 to-slate-900/40 p-4 text-white shadow-inner shadow-black/30 sm:grid-cols-4">
            <div className="rounded-xl border border-white/10 bg-white/5 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-300">Deposited in escrow</p>
              <p className="mt-1 text-2xl font-semibold text-white">
                {totalEscrowZen !== null && Number.isFinite(totalEscrowZen) ? `${totalEscrowZen.toFixed(3)} ZEN` : "—"}
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/5 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-300">Total staked</p>
              <p className="mt-1 text-2xl font-semibold text-white">{totalStakeZen.toFixed(3)} ZEN</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/5 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-300">Total to win</p>
              <p className="mt-1 text-2xl font-semibold text-white">
                {totalToWinZen > 0 ? `${totalToWinZen.toFixed(3)} ZEN` : "—"}
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/5 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-300">PnL / ROI</p>
              <p className="mt-1 text-2xl font-semibold text-white">
                {Number.isFinite(pnlZen) ? `${pnlZen >= 0 ? "+" : ""}${pnlZen.toFixed(3)} ZEN` : "—"}
              </p>
              <p className="text-xs text-slate-400">{roi !== null ? `${(roi * 100).toFixed(1)}%` : "—"}</p>
            </div>
          </div>
          {filteredPositions.map(({ position: p, bundle, bundleKey, outcomeLabel, toWinZen, quoteId, idx }) => (
            <div
              key={`${p.market_id}-${p.ticket_id ?? idx}`}
              className="rounded-2xl border border-white/10 bg-black/40 p-4 shadow-lg shadow-black/30"
            >
              {(() => {
                const txHashShort =
                  p.tx_hash && p.tx_hash.length > 16
                    ? `${p.tx_hash.slice(0, 10)}…${p.tx_hash.slice(-6)}`
                    : p.tx_hash || null;
                const txHref = explorerBase && p.tx_hash ? `${explorerBase}/${p.tx_hash}` : null;
                return (
                  <>
                    <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-white">
                      <div>
                        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Market</p>
                        <p className="font-semibold">{p.market_title ?? p.market_id}</p>
                        <p className="text-xs text-slate-400">Outcome: {outcomeLabel}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Stake</p>
                        <p className="font-mono text-white">{p.stake_zen.toFixed(3)} ZEN</p>
                      </div>
                      <div className="text-right">
                        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Status</p>
                        <div className="flex flex-col items-end gap-1">
                          <span
                            className={clsx(
                              "inline-flex items-center rounded-full px-3 py-1 text-[11px] font-semibold capitalize",
                              p.status === "settled"
                                ? "bg-emerald-500/20 text-emerald-100 border border-emerald-400/30"
                                : "bg-white/10 text-white border border-white/15",
                            )}
                          >
                            {p.status}
                          </span>
                          {p.claimable ? (
                            <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-100">
                              Claimable
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </div>
                    <div className="mt-3 grid gap-2 text-xs text-slate-300 md:grid-cols-6">
                      <span>Ticket: {p.ticket_id ?? "—"}</span>
                      <span>Created: {formatDateTime(p.created_at ?? undefined)}</span>
                      <span>Closes: {formatDateTime(p.closes_at ?? p.resolved_at ?? undefined)}</span>
                      <span>
                        Merkle root: {p.merkle_root ? `${p.merkle_root.slice(0, 8)}…${p.merkle_root.slice(-6)}` : "—"}
                      </span>
                      <span>To win: {toWinZen !== null ? `${toWinZen.toFixed(3)} ZEN` : "—"}</span>
                      <span>
                        Tx:{" "}
                        {txHref ? (
                          <a href={txHref} target="_blank" rel="noreferrer" className="underline decoration-dotted">
                            {txHashShort}
                          </a>
                        ) : txHashShort ? (
                          txHashShort
                        ) : (
                          "—"
                        )}
                      </span>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-200">
                      {p.status === "settled" && p.claimable ? (
                        <button
                          type="button"
                          className="rounded-full bg-emerald-500 px-3 py-1 font-semibold text-white hover:bg-emerald-400 disabled:cursor-not-allowed"
                          disabled={Boolean(claimingTicket) || claimPending || chainMismatch || bundlesLoading}
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
                          p.proof_request_id
                            ? `/proofs?requestId=${encodeURIComponent(p.proof_request_id)}`
                            : p.merkle_root
                              ? `/proofs?eventId=${encodeURIComponent(p.market_id)}`
                              : "/proofs"
                        }
                      >
                        View proofs
                      </Link>
                      {txHref ? (
                        <a
                          className="rounded-full bg-white/10 px-3 py-1 text-white hover:bg-white/20"
                          href={txHref}
                          target="_blank"
                          rel="noreferrer"
                        >
                          View tx
                        </a>
                      ) : null}
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
