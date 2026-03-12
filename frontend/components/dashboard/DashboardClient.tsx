"use client";

import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useState,
  useTransition,
} from "react";
import {
  useChainId,
  useConnection,
  usePublicClient,
  useReadContract,
  useSignMessage,
  useWriteContract,
} from "wagmi";
import type { Address, Hex } from "viem";
import { erc20Abi, maxUint256 } from "viem";
import { fetchPositions, fetchClaimBundles } from "@/lib/api";
import type { ClaimBundle, PositionRecord } from "@/lib/api-types";
import { defaultChain } from "@/lib/wagmi";
import { RELAYER_ESCROW_ADDRESS, ZEN_TOKEN_ADDRESS } from "@/lib/tokens";
import { formatDateTime, normalizeTxHash, roundDown } from "@/lib/formatters";
import {
  computePoseidonLeaf,
  parseBigInt,
  poseidonHashPair,
} from "@/lib/poseidon";
import Link from "next/link";
import { revealMarketClaimAbi, useClaimTicket } from "@/lib/marketContract";
import clsx from "clsx";

const POSITION_LIFECYCLE_STAGES = [
  { key: "committed", label: "Committed", description: "Stake recorded" },
  { key: "locked", label: "Locked", description: "Market closed" },
  {
    key: "pending_resolution",
    label: "Resolved",
    description: "Verifying outcome",
  },
  { key: "settled", label: "Settled", description: "Payout path ready" },
  { key: "claimed", label: "Claimed", description: "Payout received" },
] as const;

const STAGE_TOOLTIPS: Record<string, string> = {
  committed:
    "Your stake has been recorded on-chain as a private cryptographic commitment. The market is still open — others can still place bets, but your prediction stays hidden. No action needed from you yet.",
  locked:
    "Betting is now closed. The market's deadline has passed and no new stakes are accepted. The system is waiting for the oracle to report the real-world result. Your funds are safe.",
  pending_resolution:
    "The result has been posted and winners are determined. A zero-knowledge proof is being generated to verify every commitment was processed correctly — without revealing individual bets. This typically takes a few minutes.",
  settled:
    'The ZK proof has been verified on-chain — payouts are mathematically guaranteed. If you picked the winning outcome, click "Prepare to claim" then "Claim" to receive your winnings directly to your wallet.',
  claimed:
    "You successfully claimed your payout. The winnings were sent directly to your wallet address as an ERC20 transfer.",
  cancelled:
    "This market was voided before settlement. Any stake you committed will be returned. If you have questions, contact support.",
};

const STAT_TOOLTIPS = {
  escrow:
    "ZEN you have deposited into the escrow contract. This is the pool your stakes are drawn from and your winnings are returned to.",
  staked:
    "Total ZEN you have staked across all positions in the current filter view.",
  toWin:
    "Combined potential payout if all your currently open positions win.",
  pnl: "Profit or loss vs. your total stake. Positive means you are ahead; negative means you have lost more than you have won so far.",
};

type PositionLifecycleKey =
  | typeof POSITION_LIFECYCLE_STAGES[number]["key"]
  | "cancelled";

const normalizePositionStatus = (
  status: string | null | undefined
): PositionLifecycleKey => {
  const normalized = (status ?? "").toLowerCase();
  if (normalized === "locked") return "locked";
  if (normalized === "pending_resolution" || normalized === "pending")
    return "pending_resolution";
  if (normalized === "settled") return "settled";
  if (normalized === "claimed") return "claimed";
  if (normalized === "cancelled") return "cancelled";
  return "committed";
};

const shortenHash = (hash: string) => {
  const normalized = normalizeTxHash(hash) ?? hash;
  return normalized.length > 16
    ? `${normalized.slice(0, 10)}...${normalized.slice(-6)}`
    : normalized;
};
const MIN_CLAIM_GAS = 5_000_000n;
const PAGE_SIZE = 10;
const formatZenDown = (value: number, decimals = 4): string =>
  roundDown(value, decimals).toFixed(decimals);

type PositionStatusFlowProps = {
  status: string;
  claimable?: boolean | null;
  resolutionReason?: string | null;
  highlightMode: "ongoing" | "winner" | "none" | "cancelled";
  awaitingProof?: boolean;
};

function PositionStatusFlow({
  status,
  claimable,
  resolutionReason,
  highlightMode,
  awaitingProof = false,
}: PositionStatusFlowProps) {
  const [activeTooltip, setActiveTooltip] = useState<string | null>(null);
  const normalized = normalizePositionStatus(status);
  const stages =
    normalized === "cancelled"
      ? [
          ...POSITION_LIFECYCLE_STAGES,
          {
            key: "cancelled" as const,
            label: "Cancelled",
            description: resolutionReason || "Void market",
          },
        ]
      : POSITION_LIFECYCLE_STAGES;
  const currentIndex = Math.max(
    0,
    stages.findIndex((stage) => stage.key === normalized)
  );
  const isCancelled = normalized === "cancelled";
  const isFinal =
    normalized === "settled" || normalized === "claimed" || isCancelled;
  const accent = isCancelled
    ? "cancelled"
    : highlightMode === "none"
    ? "neutral"
    : "emerald";
  const connectorActiveClass =
    accent === "cancelled"
      ? "from-rose-400/80 via-rose-400/40 to-rose-500/70"
      : accent === "neutral"
      ? "from-white/15 via-white/10 to-white/15"
      : "from-emerald-400/80 via-emerald-300/40 to-emerald-400/70";
  const bubbleCompleteClass =
    accent === "cancelled"
      ? "border-rose-400/50 bg-rose-500/10 text-rose-100"
      : accent === "neutral"
      ? "border-white/10 bg-white/5 text-slate-200"
      : "border-emerald-400/50 bg-emerald-500/10 text-emerald-100";
  const bubbleCurrentClass =
    accent === "cancelled"
      ? "border-rose-300/80 bg-rose-500/20 text-rose-50 shadow-[0_0_0_2px_rgba(248,113,113,0.35)]"
      : accent === "neutral"
      ? "border-white/20 bg-white/10 text-slate-100"
      : "border-emerald-300/80 bg-emerald-500/20 text-emerald-50 shadow-[0_0_0_2px_rgba(123,240,94,0.35)]";
  const headerAccentClass =
    accent === "cancelled"
      ? "text-rose-200"
      : accent === "neutral"
      ? "text-slate-400"
      : "text-emerald-200";
  const outlineClass =
    accent === "cancelled"
      ? "border-rose-400/50 shadow-[0_0_24px_rgba(248,113,113,0.18)]"
      : highlightMode === "ongoing"
      ? "border-emerald-400/50 shadow-[0_0_22px_rgba(123,240,94,0.28)]"
      : highlightMode === "winner"
      ? "border-emerald-400/60 shadow-[0_0_28px_rgba(123,240,94,0.35)]"
      : "border-white/10";
  const nextLabel =
    stages[
      Math.min(currentIndex + 1, stages.length - 1)
    ]?.label.toLowerCase() ?? stages[stages.length - 1].label;
  const trimmedReason = resolutionReason?.trim();
  const clippedReason =
    trimmedReason && trimmedReason.length > 80
      ? `${trimmedReason.slice(0, 77)}...`
      : trimmedReason;

  return (
    <div
      className={clsx(
        "mt-3 rounded-xl border bg-gradient-to-r from-slate-900/60 via-black/60 to-slate-900/40 p-3 transition-shadow relative overflow-hidden",
        outlineClass
      )}
      onMouseLeave={() => setActiveTooltip(null)}
    >
      {highlightMode === "ongoing" ? (
        <div className="pointer-events-none absolute inset-0 bg-[length:240%_160%] opacity-35 blur-[1px] mix-blend-screen bg-[linear-gradient(120deg,rgba(123,240,94,0)_0%,rgba(123,240,94,0.22)_40%,rgba(123,240,94,0)_75%)] animate-[statusFlow_5.5s_linear_infinite]" />
      ) : null}
      <div className="flex items-center justify-between text-[11px] uppercase tracking-[0.25em] text-slate-400">
        <span>Lifecycle</span>
        <span className={clsx("text-[10px]", headerAccentClass)}>
          {isCancelled
            ? "Cancelled"
            : isFinal
            ? "All phases complete"
            : awaitingProof
            ? "Generating proof"
            : "Flowing"}
        </span>
      </div>
      <div className="relative mt-3 overflow-hidden rounded-lg border border-white/5 bg-black/40 p-3 shadow-inner shadow-black/30">
        {highlightMode === "ongoing" ? (
          <div className="pointer-events-none absolute inset-0 bg-[length:220%_140%] bg-[linear-gradient(120deg,rgba(123,240,94,0)_0%,rgba(123,240,94,0.18)_35%,rgba(123,240,94,0)_70%)] opacity-70 mix-blend-screen animate-[statusFlow_4.2s_linear_infinite]" />
        ) : null}
        <div className="relative flex flex-col items-stretch gap-2 overflow-x-hidden overflow-y-visible md:flex-row md:items-stretch md:justify-between md:gap-3 md:overflow-x-auto md:pb-1">
          {stages.map((stage, idx) => {
            const stageState =
              idx < currentIndex
                ? "complete"
                : idx === currentIndex
                ? "current"
                : "upcoming";
            return (
              <Fragment key={stage.key}>
                <div
                  className={clsx(
                    "flex min-w-0 flex-col gap-0.5 self-stretch rounded-lg border px-3 py-2 text-left transition-colors md:min-w-[140px] md:flex-1 h-full",
                    stageState === "complete"
                      ? bubbleCompleteClass
                      : stageState === "current"
                      ? bubbleCurrentClass
                      : "border-white/10 bg-white/5 text-slate-200",
                    stageState === "current" && accent === "neutral"
                      ? "opacity-85"
                      : null
                  )}
                >
                  <div className="flex items-start justify-between gap-1">
                    <span className="text-[11px] uppercase tracking-[0.2em]">{stage.label}</span>
                    <button
                      type="button"
                      aria-label={`About the ${stage.label} phase`}
                      onMouseEnter={() => setActiveTooltip(stage.key)}
                      onClick={(e) => {
                        e.stopPropagation();
                        setActiveTooltip((prev) => (prev === stage.key ? null : stage.key));
                      }}
                      className="shrink-0 cursor-pointer rounded-full text-current opacity-40 hover:opacity-80 transition-opacity focus:outline-none focus-visible:ring-1 focus-visible:ring-white/50"
                    >
                      <svg viewBox="0 0 16 16" fill="currentColor" className="h-3 w-3" aria-hidden="true">
                        <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm0 3a.75.75 0 1 1 0 1.5A.75.75 0 0 1 8 4Zm-.25 3h1.5v4.5h-1.5V7Z"/>
                      </svg>
                    </button>
                  </div>
                  <span className="text-[11px] text-slate-300 leading-snug min-h-[34px]">
                    {stage.description}
                  </span>
                </div>
                {idx < stages.length - 1 ? (
                  <div className="hidden items-center gap-2 md:flex md:flex-1 md:justify-center">
                    <div
                      className={clsx(
                        "h-[2px] w-10 rounded-full bg-gradient-to-r transition-colors md:w-full",
                        currentIndex > idx
                          ? connectorActiveClass
                          : "from-white/15 via-white/10 to-white/15"
                      )}
                    />
                    <svg
                      className={clsx(
                        "h-4 w-4",
                        currentIndex > idx
                          ? accent === "cancelled"
                            ? "text-rose-200"
                            : accent === "neutral"
                            ? "text-slate-400"
                            : "text-emerald-200"
                          : "text-slate-500"
                      )}
                      viewBox="0 0 24 24"
                      fill="none"
                      aria-hidden
                    >
                      <path
                        d="M6 5l8 7-8 7"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </div>
                ) : null}
              </Fragment>
            );
          })}
        </div>
      </div>
      {activeTooltip && STAGE_TOOLTIPS[activeTooltip] && (
        <div className="mt-2 rounded-lg border border-white/10 bg-black/50 px-3 py-2 text-[11px] text-slate-300 leading-relaxed">
          <span className="mr-1 font-semibold uppercase tracking-[0.15em] text-white/70">
            {stages.find((s) => s.key === activeTooltip)?.label}:
          </span>
          {STAGE_TOOLTIPS[activeTooltip]}
        </div>
      )}
      {(isCancelled || isFinal || awaitingProof) && (
        <p className="mt-2 text-[11px] text-slate-400">
          {isCancelled
            ? `Market cancelled${clippedReason ? ` — ${clippedReason}` : ""}.`
            : isFinal
            ? claimable
              ? "All phases cleared — claim is open."
              : "All phases cleared."
            : "Resolution set — proof in progress."}
        </p>
      )}
    </div>
  );
}

export function DashboardClient() {
  const { address, isConnected } = useConnection();
  const chainId = useChainId();
  const chainMismatch = Boolean(chainId && chainId !== defaultChain.id);
  const [positions, setPositions] = useState<PositionRecord[]>([]);
  const [loading, startTransition] = useTransition();
  const [positionsLoading, setPositionsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [escrowBalance, setEscrowBalance] = useState<string | number | null>(
    null
  );
  const [claimingTickets, setClaimingTickets] = useState<Set<string>>(
    () => new Set()
  );
  const [claimMessage, setClaimMessage] = useState<string | null>(null);
  const [claimTxHash, setClaimTxHash] = useState<string | null>(null);
  const [claimBundles, setClaimBundles] = useState<ClaimBundle[]>([]);
  const [bundleError, setBundleError] = useState<string | null>(null);
  const [bundleSignature, setBundleSignature] = useState<string | null>(null);
  const [preparingBundles, setPreparingBundles] = useState<Set<string>>(
    () => new Set()
  );
  const [statusFilter, setStatusFilter] = useState<
    "all" | "open" | "settled" | "claimable"
  >("all");
  const [sortBy, setSortBy] = useState<"recent" | "stake" | "closes">("recent");
  const [searchQuery, setSearchQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const { claimTicket, error: claimError } = useClaimTicket();
  const { mutateAsync: writeContract } = useWriteContract();
  const publicClient = usePublicClient({ chainId });
  const { mutateAsync: signMessage } = useSignMessage();
  const explorerBaseEnv = (
    process.env.NEXT_PUBLIC_EXPLORER_BASE_URL ?? ""
  ).replace(/\/+$/, "");
  const explorerBase =
    explorerBaseEnv ||
    (defaultChain.blockExplorers?.default?.url?.replace(/\/+$/, "") ?? "");
  const escrowAddress = RELAYER_ESCROW_ADDRESS;
  const tokenAddress = ZEN_TOKEN_ADDRESS;
  const [depositInput, setDepositInput] = useState<string>("0.10");
  const [withdrawInput, setWithdrawInput] = useState<string>("0.00");
  const [depositLoading, setDepositLoading] = useState(false);
  const [withdrawLoading, setWithdrawLoading] = useState(false);
  const [escrowStatus, setEscrowStatus] = useState<{
    label: string;
    txHash?: string | null;
  } | null>(null);
  const [escrowError, setEscrowError] = useState<string | null>(null);
  const { data: onchainEscrowBalance, refetch: refetchOnchainEscrow } =
    useReadContract({
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
  const { data: escrowAllowance, refetch: refetchEscrowAllowance } =
    useReadContract({
      address: tokenAddress ?? undefined,
      abi: erc20Abi,
      functionName: "allowance",
      args:
        tokenAddress && escrowAddress && address
          ? ([address as Address, escrowAddress as Address] as const)
          : undefined,
      query: {
        enabled: Boolean(tokenAddress && escrowAddress && address),
        refetchInterval: 15000,
      },
    });
  const fundingBlockedReason =
    !escrowAddress || !tokenAddress
      ? "Escrow or token address missing"
      : chainMismatch
      ? `Switch to ${defaultChain.name}`
      : null;
  const hasEscrowAllowance =
    escrowAllowance !== undefined &&
    escrowAllowance !== null &&
    escrowAllowance > 0n;
  const depositCtaLabel = hasEscrowAllowance ? "Deposit" : "Approve & Deposit";
  const depositCtaTitle = fundingBlockedReason
    ? fundingBlockedReason
    : hasEscrowAllowance
    ? "Deposit to escrow"
    : "Approve and deposit to escrow";

  const sanitizeError = (err: unknown): string => {
    const raw = err instanceof Error ? err.message : String(err);
    const [message] = raw.split("Version:");
    return message.trim() || "Transaction failed";
  };
  const waitForReceipt = async (hash: Hex, label: string) => {
    if (!publicClient) return;
    const receipt = await publicClient.waitForTransactionReceipt({ hash });
    if (receipt.status !== "success") {
      throw new Error(`${label} reverted`);
    }
  };
  const sanitizeUserActionError = useCallback((err: unknown): string => {
    const raw = err instanceof Error ? err.message : String(err);
    const [message] = raw.split("Version:");
    const cleaned = message.replace(/^Details:\s*/i, "").trim();
    return cleaned || "Action cancelled";
  }, []);
  const txHref = useCallback(
    (hash?: string | null) => {
      if (!hash || !explorerBase) return null;
      const normalized = normalizeTxHash(hash);
      if (!normalized) return null;
      return `${explorerBase}/tx/${normalized}`;
    },
    [explorerBase]
  );

  const load = useMemo(
    () => async (wallet: string) => {
      setPositionsLoading(true);
      try {
        setError(null);
        const res = await fetchPositions(wallet);
        setPositions(res.positions || []);
        setEscrowBalance(res.escrowBalance ?? null);
        if (res.error) {
          setError(res.error);
        }
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load positions"
        );
      } finally {
        setPositionsLoading(false);
      }
    },
    []
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
    setDepositLoading(true);
    try {
      if (!escrowAllowance || escrowAllowance < amountWei) {
        const approveHash = await writeContract({
          address: tokenAddress as Address,
          abi: erc20Abi,
          functionName: "approve",
          args: [escrowAddress as Address, maxUint256],
          chainId,
        });
        setEscrowStatus({ label: "Approve tx", txHash: approveHash as string });
        await waitForReceipt(approveHash as Hex, "Approval");
      }
      const depositHash = await writeContract({
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
      setEscrowStatus({ label: "Deposit tx", txHash: depositHash as string });
      await waitForReceipt(depositHash as Hex, "Deposit");
      await refetchTokenBalance();
      await refetchEscrowAllowance();
      await refetchOnchainEscrow();
      await load(address);
    } catch (err) {
      setEscrowError(sanitizeError(err));
    } finally {
      setDepositLoading(false);
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
    setWithdrawLoading(true);
    try {
      const withdrawHash = await writeContract({
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
      setEscrowStatus({ label: "Withdraw tx", txHash: withdrawHash as string });
      await waitForReceipt(withdrawHash as Hex, "Withdraw");
      await refetchTokenBalance();
      await refetchEscrowAllowance();
      await refetchOnchainEscrow();
      await load(address);
    } catch (err) {
      setEscrowError(sanitizeError(err));
    } finally {
      setWithdrawLoading(false);
    }
  };

  useEffect(() => {
    if (!address) {
      setPositions([]);
      setClaimBundles([]);
      setBundleSignature(null);
      setPreparingBundles(new Set());
      setClaimMessage(null);
      setClaimTxHash(null);
      setEscrowStatus(null);
      setClaimingTickets(new Set());
      return;
    }
    startTransition(() => {
      void load(address);
    });
  }, [address, load]);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [statusFilter, sortBy, searchQuery]);

  const ensureBundleSignature = async () => {
    if (!address) return null;
    const message = `claim-bundles:${address.toLowerCase()}`;
    const signature =
      bundleSignature && bundleSignature.length > 0
        ? bundleSignature
        : await signMessage({ message });
    if (!bundleSignature) {
      setBundleSignature(signature);
    }
    return signature;
  };

  const handlePrepareBundle = async (marketId: string, ticketId?: number | null) => {
    if (!address) return;
    const key = `${marketId}:${ticketId ?? "na"}`;
    setPreparingBundles((prev) => {
      const next = new Set(prev);
      next.add(key);
      return next;
    });
    try {
      const signature = await ensureBundleSignature();
      if (!signature) return;
      const res = await fetchClaimBundles(address, signature);
      if (res.status === "pending") {
        setClaimMessage("Your proof is being generated. Please check back in a few minutes.");
        return;
      }
      if (res.error) {
        setBundleError(sanitizeUserActionError(res.error));
        return;
      }
      if (Array.isArray(res.bundles)) {
        setClaimBundles(res.bundles);
        setClaimMessage(null);
      }
    } catch (err) {
      const message = sanitizeUserActionError(err) || "Failed to load claim bundles";
      setBundleError(message);
    } finally {
      setPreparingBundles((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  const handleClaim = async (marketId: string, ticketId?: number | null) => {
    if (!address) return;
    const key = `${marketId}:${ticketId ?? "na"}`;
    setClaimTxHash(null);
    let bundle = bundleLookup.get(key);
    if (!bundle) {
      setClaimMessage("Payment data not loaded for this market.");
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
    let ticketIdValue: bigint;
    let outcomeIdValue: bigint;
    let amountValue: bigint;
    let payoutValue: bigint;
    try {
      ticketIdValue = parseBigInt(bundle.ticketId);
      outcomeIdValue = parseBigInt(bundle.outcomeId);
      amountValue = parseBigInt(bundle.amountWei);
      payoutValue = parseBigInt(bundle.payoutWei);
      const userValue = parseBigInt(bundle.user);
      const saltValue = parseBigInt(bundle.salt);
      const leafValue = computePoseidonLeaf(
        ticketIdValue,
        outcomeIdValue,
        amountValue,
        payoutValue,
        userValue,
        saltValue
      );
      const storedLeaf = parseBigInt(bundle.leaf);
      if (leafValue !== storedLeaf) {
        setClaimMessage("Bundle integrity check failed (leaf mismatch).");
        return;
      }
      let computed = leafValue;
      let idx = ticketIdValue;
      for (const sibling of bundle.merkleProof || []) {
        const siblingValue = parseBigInt(sibling);
        computed =
          (idx & 1n) === 1n
            ? poseidonHashPair(siblingValue, computed)
            : poseidonHashPair(computed, siblingValue);
        idx >>= 1n;
      }
      const providedRoot = (bundle.commitmentsRoot ?? "").trim();
      if (providedRoot) {
        const rootValue = parseBigInt(providedRoot);
        if (computed !== rootValue) {
          setClaimMessage("Bundle integrity check failed (root mismatch).");
          return;
        }
      }
    } catch (err) {
      setClaimMessage(
        err instanceof Error
          ? `Bundle validation failed: ${err.message}`
          : "Bundle validation failed"
      );
      return;
    }
    setClaimingTickets((prev) => {
      const next = new Set(prev);
      next.add(key);
      return next;
    });
    setClaimMessage(null);
    try {
      let gasLimit = MIN_CLAIM_GAS;
      if (publicClient) {
        try {
          const estimate = await publicClient.estimateContractGas({
            address: bundle.marketAddress as Address,
            abi: revealMarketClaimAbi,
            functionName: "claim",
            args: [
              bundle.user as Address,
              ticketIdValue,
              outcomeIdValue,
              amountValue,
              payoutValue,
              (bundle.salt ?? "0x") as Hex,
              (bundle.merkleProof ?? []) as Hex[],
            ],
            account: bundle.user as Address,
          });
          const buffered = estimate + estimate / 4n;
          gasLimit = buffered > MIN_CLAIM_GAS ? buffered : MIN_CLAIM_GAS;
        } catch {
          gasLimit = MIN_CLAIM_GAS;
        }
      }
      setClaimMessage("Claiming...");
      const txHash = await claimTicket({
        marketAddress: bundle.marketAddress as Address,
        user: bundle.user as Address,
        ticketId: ticketIdValue,
        outcomeId: outcomeIdValue,
        amountWei: amountValue,
        payoutWei: payoutValue,
        salt: (bundle.salt ?? "0x") as Hex,
        merkleProof: (bundle.merkleProof ?? []) as Hex[],
        gasLimit,
      });
      setClaimMessage("Claim sent");
      setClaimBundles((prev) =>
        prev.filter((b) => `${b.marketId}:${b.ticketId}` !== key)
      );
      setClaimTxHash(txHash as string);
      setPositions((prev) =>
        prev.map((position) =>
          `${position.market_id}:${position.ticket_id ?? "na"}` === key
            ? {
                ...position,
                status: "claimed",
                claimable: false,
                tx_hash: txHash as string,
              }
            : position
        )
      );
      await refetchTokenBalance();
    } catch (err) {
      setClaimMessage(err instanceof Error ? err.message : "Claim failed");
    } finally {
      setClaimingTickets((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  const normalizedEscrow =
    escrowBalance !== null ? Number(escrowBalance) : null;
  const escrowDisplay =
    normalizedEscrow !== null && Number.isFinite(normalizedEscrow)
      ? formatZenDown(normalizedEscrow / 1e18)
      : "—";
  const escrowBalanceBigInt =
    onchainEscrowBalance !== undefined && onchainEscrowBalance !== null
      ? BigInt(onchainEscrowBalance)
      : null;
  const normalizedOnchainEscrow =
    escrowBalanceBigInt !== null ? Number(escrowBalanceBigInt) : null;
  const normalizeWei = useCallback((value: unknown): bigint | null => {
    if (value === undefined || value === null) return null;
    try {
      if (typeof value === "bigint") return value;
      if (typeof value === "number" && Number.isFinite(value))
        return BigInt(Math.floor(value));
      const asString = String(value);
      if (!asString) return null;
      return BigInt(asString);
    } catch {
      return null;
    }
  }, []);
  const derivedPositions = useMemo(() => {
    const parseDate = (value?: string | null) => {
      if (!value) return 0;
      const ts = Date.parse(value);
      return Number.isNaN(ts) ? 0 : ts;
    };
    return positions.map((p, idx) => {
      const bundleKey = `${p.market_id}:${p.ticket_id ?? "na"}`;
      const bundle = bundleLookup.get(bundleKey);

      const market = p.market_summary ?? null;
      const outcomes = market?.outcomes ?? [];
      const outcomeLabel =
        p.outcome_label ?? outcomes[p.outcome_id] ?? `Outcome ${p.outcome_id}`;
      const marketTitle =
        p.market_title ??
        market?.title ??
        (outcomes.length > 1 ? outcomes.join("/") : p.market_id);
      const potentialZen =
        typeof p.payout_zen === "number" && Number.isFinite(p.payout_zen)
          ? p.payout_zen
          : typeof p.potential_payout_zen === "number" &&
            Number.isFinite(p.potential_payout_zen)
          ? p.potential_payout_zen
          : null;
      const potentialWeiFromPosition =
        normalizeWei(p.payout_wei) ??
        normalizeWei(p.potential_payout_wei);
      const bundlePayoutWei = bundle
        ? normalizeWei(bundle.payoutWei ?? bundle.amountWei)
        : null;
      const hasResolution =
        p.winning_outcome_id !== null &&
        p.winning_outcome_id !== undefined &&
        Number.isFinite(p.winning_outcome_id);
      const isWinner = hasResolution && p.winning_outcome_id === p.outcome_id;
      const settlementPending = !hasResolution && Boolean(p.resolved_at);
      let toWinWei: bigint | null = null;
      if (bundlePayoutWei !== null) {
        toWinWei = bundlePayoutWei;
      } else if (p.claimable) {
        toWinWei = null;
      } else if (potentialWeiFromPosition !== null) {
        toWinWei = potentialWeiFromPosition;
      } else if (potentialZen !== null) {
        toWinWei = normalizeWei(Math.round(potentialZen * 1e18));
      }
      if (hasResolution && !isWinner) {
        toWinWei = 0n;
      }
      const price =
        market && Array.isArray(market.outcome_prices)
          ? market.outcome_prices[p.outcome_id]
          : null;
      const toWinZen =
        toWinWei !== null
          ? Number(toWinWei) / 1e18
          : !hasResolution &&
            !settlementPending &&
            price &&
            Number.isFinite(price) &&
            price > 0
          ? p.stake_zen / price
          : null;
      const createdAtTs = parseDate(p.created_at);
      const closesAtTs = parseDate(p.closes_at);
      return {
        position: p,
        bundle,
        bundleKey,
        outcomeLabel,
        toWinZen,
        idx,
        marketTitle,
        createdAtTs,
        closesAtTs,
      };
    });
  }, [bundleLookup, normalizeWei, positions]);
  const filteredPositions = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return derivedPositions
      .filter(({ position }) => {
        if (statusFilter === "open" && position.status === "settled")
          return false;
        if (statusFilter === "settled" && position.status !== "settled")
          return false;
        if (statusFilter === "claimable" && !position.claimable) return false;
        if (query.length === 0) return true;
        const market = position.market_summary ?? null;
        const candidateTitle =
          position.market_title ??
          market?.title ??
          (market?.outcomes && market.outcomes.length > 1
            ? market.outcomes.join("/")
            : position.market_id);
        return candidateTitle.toLowerCase().includes(query);
      })
      .sort((a, b) => {
        if (sortBy === "stake") {
          return (b.position.stake_zen || 0) - (a.position.stake_zen || 0);
        }
        if (sortBy === "closes") {
          return b.closesAtTs - a.closesAtTs;
        }
        return b.createdAtTs - a.createdAtTs;
      });
  }, [derivedPositions, searchQuery, sortBy, statusFilter]);
  const filterCounts = useMemo(
    () => ({
      all: derivedPositions.length,
      open: derivedPositions.filter(({ position }) => position.status !== "settled").length,
      settled: derivedPositions.filter(({ position }) => position.status === "settled").length,
      claimable: derivedPositions.filter(({ position }) => Boolean(position.claimable)).length,
    }),
    [derivedPositions]
  );
  const visiblePositions = filteredPositions.slice(0, visibleCount);
  const totalStakeZen = filteredPositions.reduce(
    (acc, { position }) =>
      acc + (Number.isFinite(position.stake_zen) ? position.stake_zen : 0),
    0
  );
  const totalToWinZen = filteredPositions.reduce(
    (acc, { toWinZen }) =>
      acc + (toWinZen !== null && Number.isFinite(toWinZen) ? toWinZen : 0),
    0
  );
  const totalEscrowZen =
    normalizedEscrow !== null && Number.isFinite(normalizedEscrow)
      ? normalizedEscrow / 1e18
      : normalizedOnchainEscrow !== null &&
        Number.isFinite(normalizedOnchainEscrow)
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
      <div className="rounded-3xl border border-[#7c84ff]/20 bg-slate-950/60 p-4 shadow-[0_0_32px_rgba(124,132,255,0.08),inset_0_1px_0_rgba(255,255,255,0.06)]">
        <div className="flex items-center justify-between">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
            Escrow Balance
          </p>
          <details className="text-[11px] text-slate-600">
            <summary className="cursor-pointer select-none hover:text-slate-400 transition-colors">
              details
            </summary>
            <p className="mt-1 break-all text-slate-500">
              {RELAYER_ESCROW_ADDRESS ?? "n/a"} &middot;{" "}
              {chainMismatch ? (
                <span className="text-rose-400">Wrong network</span>
              ) : (
                defaultChain.name
              )}
            </p>
          </details>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <span className="text-2xl font-semibold text-white">
            {escrowDisplay} ZEN
          </span>
          {!ZEN_TOKEN_ADDRESS && (
            <span className="text-xs text-amber-300">(ZEN token missing)</span>
          )}
          {chainMismatch && (
            <span className="rounded-full border border-rose-400/30 bg-rose-500/10 px-2 py-0.5 text-[11px] text-rose-300">
              Wrong network
            </span>
          )}
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <div className="rounded-2xl border border-[#7bf05e]/20 bg-gradient-to-br from-[#7bf05e]/10 via-black/60 to-black/80 p-4 shadow-[inset_0_1px_0_rgba(123,240,94,0.12),0_0_24px_rgba(123,240,94,0.07)]">
            <div className="flex items-center justify-between text-slate-300">
              <p className="text-xs uppercase tracking-[0.2em] text-emerald-200">
                Deposit
              </p>
              <span className="text-[11px] text-slate-400">
                Wallet:{" "}
                {tokenBalance !== undefined && tokenBalance !== null
                  ? `${formatZenDown(Number(tokenBalance) / 1e18)} ZEN`
                  : "—"}
              </span>
            </div>
            <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
              <div className="relative flex-1">
                <input
                  type="number"
                  name="escrowDepositAmount"
                  value={depositInput}
                  onChange={(e) => setDepositInput(e.target.value)}
                  className="w-full rounded-lg border border-emerald-500/40 bg-slate-900/70 px-3 py-2 pr-14 text-white shadow-sm shadow-emerald-900/30 focus:border-emerald-300 focus:outline-none"
                  step="0.01"
                  min="0"
                  aria-label="Deposit amount"
                />
                {tokenBalance !== undefined && tokenBalance !== null && (
                  <button
                    type="button"
                    onClick={() => setDepositInput(formatZenDown(Number(tokenBalance) / 1e18, 4))}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-300 hover:text-emerald-100 transition-colors"
                  >
                    Max
                  </button>
                )}
              </div>
              <button
                type="button"
                onClick={handleDeposit}
                className="flex w-full items-center justify-center gap-1.5 whitespace-nowrap rounded-full bg-emerald-500 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-white shadow-lg shadow-emerald-900/50 transition hover:-translate-y-[1px] hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-emerald-800/60 sm:w-auto"
                disabled={Boolean(fundingBlockedReason) || depositLoading}
                title={depositCtaTitle}
              >
                {depositLoading && (
                  <svg className="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                  </svg>
                )}
                {depositCtaLabel}
              </button>
            </div>
            <p className="mt-1 text-[11px] text-emerald-100/80">
              MetaMask may show an approval first (lets the escrow spend your
              ZEN), then the actual deposit. You will only see the approval once
              unless you lower your allowance.
            </p>
            {fundingBlockedReason && (
              <p className="mt-2 text-xs text-amber-200">
                {fundingBlockedReason}
              </p>
            )}
            {escrowStatus && (
              <p className="mt-2 text-xs text-emerald-200">
                {escrowStatus.label}
                {escrowStatus.txHash ? (
                  <>
                    {": "}
                    {txHref(escrowStatus.txHash) ? (
                      <a
                        className="underline underline-offset-4"
                        href={txHref(escrowStatus.txHash) ?? undefined}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {shortenHash(escrowStatus.txHash)}
                      </a>
                    ) : (
                      shortenHash(escrowStatus.txHash)
                    )}
                  </>
                ) : null}
              </p>
            )}
            {escrowError && (
              <p className="mt-2 text-xs text-rose-300">{escrowError}</p>
            )}
          </div>
          <div className="rounded-2xl border border-[#7c84ff]/15 bg-gradient-to-br from-[#7c84ff]/10 via-black/60 to-black/80 p-4 shadow-[inset_0_1px_0_rgba(124,132,255,0.08),0_0_20px_rgba(124,132,255,0.05)]">
            <div className="flex items-center justify-between text-slate-300">
              <p className="text-xs uppercase tracking-[0.2em] text-slate-200">
                Withdraw
              </p>
              <span className="text-[11px] text-slate-400">
                Escrow:{" "}
                {normalizedOnchainEscrow !== null &&
                Number.isFinite(normalizedOnchainEscrow)
                  ? `${formatZenDown(normalizedOnchainEscrow / 1e18)} ZEN`
                  : "—"}
              </span>
            </div>
            <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
              <div className="relative flex-1">
                <input
                  type="number"
                  name="escrowWithdrawAmount"
                  value={withdrawInput}
                  onChange={(e) => setWithdrawInput(e.target.value)}
                  className="w-full rounded-lg border border-white/20 bg-slate-900/70 px-3 py-2 pr-14 text-white shadow-sm shadow-black/40 focus:border-white/60 focus:outline-none"
                  step="0.01"
                  min="0"
                  aria-label="Withdraw amount"
                />
                {normalizedOnchainEscrow !== null && normalizedOnchainEscrow > 0 && (
                  <button
                    type="button"
                    onClick={() => setWithdrawInput(formatZenDown(normalizedOnchainEscrow / 1e18, 4))}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-300 hover:text-white transition-colors"
                  >
                    Max
                  </button>
                )}
              </div>
              <button
                type="button"
                onClick={handleWithdraw}
                className="flex w-full items-center justify-center gap-1.5 whitespace-nowrap rounded-full bg-white/15 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-white shadow-lg shadow-black/50 transition hover:-translate-y-[1px] hover:bg-white/25 disabled:cursor-not-allowed disabled:bg-white/10 sm:w-auto"
                disabled={
                  withdrawLoading ||
                  chainMismatch ||
                  !RELAYER_ESCROW_ADDRESS ||
                  !ZEN_TOKEN_ADDRESS ||
                  !normalizedOnchainEscrow ||
                  normalizedOnchainEscrow <= 0
                }
                title={chainMismatch ? `Switch to ${defaultChain.name}` : ""}
              >
                {withdrawLoading && (
                  <svg className="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                  </svg>
                )}
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
      ) : positionsLoading || loading ? (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-32 animate-pulse rounded-2xl border border-white/10 bg-white/5" />
          ))}
        </div>
      ) : positions.length === 0 ? (
        <div className="rounded-3xl border border-white/10 bg-slate-950/60 p-10 text-center">
          <p className="mb-4 text-slate-400">No positions yet.</p>
          <Link
            href="/"
            className="rounded-full border border-emerald-400/30 bg-emerald-500/20 px-4 py-2 text-sm text-emerald-200 transition hover:bg-emerald-500/30"
          >
            Browse markets
          </Link>
        </div>
      ) : (
        <div className="space-y-4">
          {bundleError && (
            <div className="flex items-start justify-between gap-3 rounded-2xl border border-amber-400/40 bg-amber-500/10 p-3 text-amber-100">
              <p className="flex-1 text-sm">{bundleError}</p>
              <div className="flex shrink-0 items-center gap-2">
                <button
                  type="button"
                  className="text-xs text-amber-300 underline underline-offset-2 hover:text-amber-100"
                  onClick={() => { setBundleError(null); setBundleSignature(null); }}
                >
                  Retry
                </button>
                <button
                  type="button"
                  aria-label="Dismiss error"
                  className="text-amber-400 transition-colors hover:text-amber-100"
                  onClick={() => setBundleError(null)}
                >
                  <svg viewBox="0 0 16 16" fill="currentColor" className="h-4 w-4" aria-hidden="true">
                    <path d="M4.22 4.22a.75.75 0 0 1 1.06 0L8 6.94l2.72-2.72a.75.75 0 1 1 1.06 1.06L9.06 8l2.72 2.72a.75.75 0 1 1-1.06 1.06L8 9.06l-2.72 2.72a.75.75 0 0 1-1.06-1.06L6.94 8 4.22 5.28a.75.75 0 0 1 0-1.06Z"/>
                  </svg>
                </button>
              </div>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-white/10 bg-gradient-to-r from-slate-900/70 via-slate-900/40 to-slate-800/40 px-4 py-3 shadow-inner shadow-black/30">
            <input
              type="search"
              name="positionsSearch"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search markets"
              className="w-full min-w-0 flex-1 rounded-lg border border-white/20 bg-black/30 px-3 py-2 text-sm text-white shadow-inner shadow-black/40 focus:border-white/60 focus:outline-none sm:min-w-[200px] sm:w-auto"
            />
            <div className="flex flex-wrap items-center gap-2">
              {(["all", "open", "settled", "claimable"] as const).map(
                (filter) => (
                  <button
                    key={filter}
                    type="button"
                    onClick={() => setStatusFilter(filter)}
                    className={clsx(
                      "rounded-full px-3 py-2 text-xs font-semibold uppercase tracking-wide transition sm:py-1",
                      statusFilter === filter
                        ? "bg-white/80 text-black shadow"
                        : "bg-white/10 text-white hover:bg-white/20"
                    )}
                  >
                    {filter}{" "}
                    <span className={clsx("font-normal", statusFilter === filter ? "text-black/50" : "text-white/40")}>
                      ({filterCounts[filter]})
                    </span>
                  </button>
                )
              )}
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-300">
              Sort
              <div className="relative">
                <select
                  name="positionsSort"
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
                  className="appearance-none rounded-full border border-white/20 bg-white/10 px-3 py-2 pr-8 text-xs font-semibold uppercase tracking-wide text-white shadow shadow-black/30 transition focus:border-white/60 focus:outline-none sm:py-1"
                >
                  <option value="recent">Most recent</option>
                  <option value="stake">Stake size</option>
                  <option value="closes">Closing time</option>
                </select>
                <svg
                  aria-hidden="true"
                  viewBox="0 0 20 20"
                  className="pointer-events-none absolute right-3 top-1/2 h-3 w-3 -translate-y-1/2 text-white/70"
                  fill="currentColor"
                >
                  <path d="M5.25 7.5L10 12.25L14.75 7.5H5.25Z" />
                </svg>
              </div>
            </label>
          </div>
          <div className="grid gap-3 rounded-2xl border border-[#7c84ff]/15 bg-gradient-to-r from-[#0c27b1]/30 via-slate-900/60 to-[#7c84ff]/10 p-4 text-white shadow-[inset_0_1px_0_rgba(124,132,255,0.10),0_0_28px_rgba(12,39,177,0.12)] sm:grid-cols-4">
            <div className="group relative rounded-xl border border-white/10 bg-white/5 p-3">
              <div className="flex items-center gap-1">
                <p className="text-[11px] uppercase tracking-[0.25em] text-slate-300">
                  Deposited in escrow
                </p>
                <svg viewBox="0 0 16 16" fill="currentColor" className="h-3 w-3 shrink-0 text-slate-500 transition-colors group-hover:text-slate-300" aria-hidden="true">
                  <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm0 3a.75.75 0 1 1 0 1.5A.75.75 0 0 1 8 4Zm-.25 3h1.5v4.5h-1.5V7Z"/>
                </svg>
              </div>
              <div className="pointer-events-none absolute bottom-full left-0 z-20 mb-1.5 w-56 rounded-lg border border-white/10 bg-slate-900 px-3 py-2 text-[11px] text-slate-300 leading-relaxed opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
                {STAT_TOOLTIPS.escrow}
              </div>
              <p className="mt-1 text-2xl font-semibold text-white">
                {totalEscrowZen !== null && Number.isFinite(totalEscrowZen)
                  ? `${formatZenDown(totalEscrowZen)} ZEN`
                  : "—"}
              </p>
            </div>
            <div className="group relative rounded-xl border border-white/10 bg-white/5 p-3">
              <div className="flex items-center gap-1">
                <p className="text-[11px] uppercase tracking-[0.25em] text-slate-300">
                  Total staked
                </p>
                <svg viewBox="0 0 16 16" fill="currentColor" className="h-3 w-3 shrink-0 text-slate-500 transition-colors group-hover:text-slate-300" aria-hidden="true">
                  <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm0 3a.75.75 0 1 1 0 1.5A.75.75 0 0 1 8 4Zm-.25 3h1.5v4.5h-1.5V7Z"/>
                </svg>
              </div>
              <div className="pointer-events-none absolute bottom-full left-0 z-20 mb-1.5 w-56 rounded-lg border border-white/10 bg-slate-900 px-3 py-2 text-[11px] text-slate-300 leading-relaxed opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
                {STAT_TOOLTIPS.staked}
              </div>
              <p className="mt-1 text-2xl font-semibold text-white">
                {formatZenDown(totalStakeZen)} ZEN
              </p>
            </div>
            <div className="group relative rounded-xl border border-white/10 bg-white/5 p-3">
              <div className="flex items-center gap-1">
                <p className="text-[11px] uppercase tracking-[0.25em] text-slate-300">
                  Total to win
                </p>
                <svg viewBox="0 0 16 16" fill="currentColor" className="h-3 w-3 shrink-0 text-slate-500 transition-colors group-hover:text-slate-300" aria-hidden="true">
                  <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm0 3a.75.75 0 1 1 0 1.5A.75.75 0 0 1 8 4Zm-.25 3h1.5v4.5h-1.5V7Z"/>
                </svg>
              </div>
              <div className="pointer-events-none absolute bottom-full left-0 z-20 mb-1.5 w-56 rounded-lg border border-white/10 bg-slate-900 px-3 py-2 text-[11px] text-slate-300 leading-relaxed opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
                {STAT_TOOLTIPS.toWin}
              </div>
              <p className="mt-1 text-2xl font-semibold text-white">
                {totalToWinZen > 0 ? `${formatZenDown(totalToWinZen)} ZEN` : "—"}
              </p>
            </div>
            <div className="group relative rounded-xl border border-white/10 bg-white/5 p-3">
              <div className="flex items-center gap-1">
                <p className="text-[11px] uppercase tracking-[0.25em] text-slate-300">
                  PnL / ROI
                </p>
                <svg viewBox="0 0 16 16" fill="currentColor" className="h-3 w-3 shrink-0 text-slate-500 transition-colors group-hover:text-slate-300" aria-hidden="true">
                  <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm0 3a.75.75 0 1 1 0 1.5A.75.75 0 0 1 8 4Zm-.25 3h1.5v4.5h-1.5V7Z"/>
                </svg>
              </div>
              <div className="pointer-events-none absolute bottom-full left-0 z-20 mb-1.5 w-56 rounded-lg border border-white/10 bg-slate-900 px-3 py-2 text-[11px] text-slate-300 leading-relaxed opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
                {STAT_TOOLTIPS.pnl}
              </div>
              <p
                className={clsx(
                  "mt-1 text-2xl font-semibold",
                  Number.isFinite(pnlZen)
                    ? pnlZen >= 0
                      ? "text-emerald-300"
                      : "text-rose-300"
                    : "text-white"
                )}
              >
                {Number.isFinite(pnlZen)
                  ? `${pnlZen >= 0 ? "+" : ""}${formatZenDown(pnlZen)} ZEN`
                  : "—"}
              </p>
              <p
                className={clsx(
                  "text-xs",
                  roi !== null ? (roi >= 0 ? "text-emerald-400" : "text-rose-400") : "text-slate-400"
                )}
              >
                {roi !== null ? `${(roi * 100).toFixed(1)}%` : "—"}
              </p>
            </div>
          </div>
          {(statusFilter !== "all" || searchQuery.trim().length > 0) && (
            <p className="text-right text-[11px] text-slate-500">
              Stats reflect current filter &middot; {filteredPositions.length} of {derivedPositions.length} positions
            </p>
          )}
          <div className="flex items-center justify-between">
            <p className="text-[11px] text-slate-500">
              Showing {Math.min(visibleCount, filteredPositions.length)} of {filteredPositions.length} positions
            </p>
            <button
              type="button"
              aria-label="Refresh positions"
              onClick={() => address && void load(address)}
              disabled={positionsLoading}
              className="rounded-full p-1.5 text-slate-500 transition-colors hover:bg-white/10 hover:text-slate-300 disabled:opacity-40"
            >
              <svg viewBox="0 0 24 24" fill="currentColor" className={clsx("h-4 w-4", positionsLoading && "animate-spin")} aria-hidden="true">
                <path fillRule="evenodd" d="M4.755 10.059a7.5 7.5 0 0 1 12.548-3.364l1.903 1.903h-3.183a.75.75 0 1 0 0 1.5h4.992a.75.75 0 0 0 .75-.75V4.356a.75.75 0 0 0-1.5 0v3.18l-1.9-1.9A9 9 0 0 0 3.306 9.67a.75.75 0 1 0 1.45.388Zm15.408 3.352a.75.75 0 0 0-.919.53 7.5 7.5 0 0 1-12.548 3.364l-1.902-1.903h3.183a.75.75 0 0 0 0-1.5H2.984a.75.75 0 0 0-.75.75v4.992a.75.75 0 0 0 1.5 0v-3.18l1.9 1.9a9 9 0 0 0 15.059-4.035.75.75 0 0 0-.53-.918Z" clipRule="evenodd"/>
              </svg>
            </button>
          </div>
          {visiblePositions.map(
            ({
              position: p,
              bundle,
              bundleKey,
              outcomeLabel,
              toWinZen,
              idx,
              marketTitle,
            }) => {
              const hasResolution =
                p.winning_outcome_id !== null &&
                p.winning_outcome_id !== undefined &&
                Number.isFinite(p.winning_outcome_id);
              const isWinner =
                hasResolution && p.winning_outcome_id === p.outcome_id;
              const awaitingProof = !hasResolution && Boolean(p.resolved_at);
              const isOngoing =
                !hasResolution &&
                p.status !== "claimed" &&
                p.status !== "cancelled";
              const highlightMode =
                p.status === "cancelled"
                  ? "cancelled"
                  : isOngoing
                  ? "ongoing"
                  : isWinner
                  ? "winner"
                  : "none";
              return (
                <div
                  key={`${p.market_id}-${p.ticket_id ?? idx}`}
                  className={`rounded-2xl border border-white/[0.07] bg-black/40 p-4 shadow-[0_4px_24px_rgba(1,3,20,0.55),inset_0_1px_0_rgba(255,255,255,0.04)]${
                    p.status === "cancelled"
                      ? " border-l-2 border-l-amber-500/40"
                      : hasResolution && p.status !== "claimed"
                        ? isWinner
                          ? " border-l-2 border-l-emerald-500/50"
                          : " border-l-2 border-l-rose-500/40"
                        : ""
                  }`}
                >
                  {(() => {
                    const normalizedTxHash = normalizeTxHash(p.tx_hash);
                    const txHref =
                      explorerBase && normalizedTxHash
                        ? `${explorerBase}/tx/${normalizedTxHash}`
                        : null;
                    return (
                      <>
                        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-white">
                          <div>
                            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
                              Market
                            </p>
                            <p className="break-words font-semibold">
                              {marketTitle}
                            </p>
                            <p className="text-xs text-slate-400">
                              Outcome: {outcomeLabel}
                            </p>
                          </div>
                          <div className="flex flex-col items-end gap-1.5">
                            <div className="text-right">
                              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
                                Stake
                              </p>
                              <p className="font-mono text-white">
                                {formatZenDown(p.stake_zen)} ZEN
                              </p>
                            </div>
                          </div>
                          <div className="text-right">
                            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
                              To win
                            </p>
                            <p className="font-mono text-white">
                              {toWinZen !== null
                                ? `${formatZenDown(toWinZen)} ZEN`
                                : p.claimable
                                ? "Prepare to claim"
                                : "—"}
                            </p>
                            {p.claimable && toWinZen === null ? (
                              <span className="mt-1 block text-[10px] italic text-slate-400">
                                proof needed
                              </span>
                            ) : null}
                            {p.claimable ? (
                              <>
                                <span className="mt-1 inline-flex rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-100">
                                  Claimable
                                </span>
                                {isWinner ? (
                                  <span className="mt-1 block text-[10px] uppercase tracking-[0.2em] text-emerald-200">
                                    Payout ready
                                  </span>
                                ) : null}
                              </>
                            ) : p.status === "claimed" ? (
                              <span className="mt-1 inline-flex rounded-full bg-sky-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-sky-100">
                                Claimed
                              </span>
                            ) : null}
                          </div>
                        </div>
                        <PositionStatusFlow
                          status={p.status}
                          claimable={p.claimable}
                          resolutionReason={p.resolution_reason}
                          highlightMode={highlightMode}
                          awaitingProof={awaitingProof}
                        />
                        <div className="mt-3 grid gap-2 text-xs text-slate-300 md:grid-cols-3">
                          <span>
                            Created: {formatDateTime(p.created_at ?? undefined)}
                          </span>
                          <span>
                            Closes:{" "}
                            {formatDateTime(
                              p.closes_at ?? p.resolved_at ?? undefined
                            )}
                          </span>
                          {p.merkle_root && (
                            <span>
                              Merkle root: {p.merkle_root.slice(0, 8)}...{p.merkle_root.slice(-6)}
                            </span>
                          )}
                          {p.claimed_at && (
                            <span>
                              Claimed: {formatDateTime(p.claimed_at)}
                            </span>
                          )}
                        </div>
                        {p.status === "settled" && p.claimable && (
                          <p className="mt-3 text-[11px] leading-relaxed text-slate-400">
                            <span className="font-semibold text-slate-300">Ready to claim.</span>{" "}
                            {bundle
                              ? "Payment data loaded — submit the on-chain claim transaction below."
                              : "Step 1: fetch your proof data from the server. Step 2: submit the claim transaction on-chain."}
                          </p>
                        )}
                        <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-200">
                          {p.status === "settled" && p.claimable ? (
                            bundle ? (
                              <button
                                type="button"
                                className="flex items-center gap-1.5 rounded-full bg-emerald-500 px-3 py-2 font-semibold text-white hover:bg-emerald-400 disabled:cursor-not-allowed sm:py-1"
                                disabled={
                                  chainMismatch ||
                                  claimingTickets.has(bundleKey)
                                }
                                onClick={() =>
                                  handleClaim(p.market_id, p.ticket_id)
                                }
                              >
                                {claimingTickets.has(bundleKey) && (
                                  <svg className="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                                  </svg>
                                )}
                                {claimingTickets.has(bundleKey)
                                  ? "Claiming..."
                                  : "Claim"}
                              </button>
                            ) : (
                              <button
                                type="button"
                                className="flex items-center gap-1.5 rounded-full bg-emerald-500 px-3 py-2 font-semibold text-white hover:bg-emerald-400 disabled:cursor-not-allowed sm:py-1"
                                disabled={
                                  chainMismatch ||
                                  preparingBundles.has(bundleKey)
                                }
                                onClick={() =>
                                  handlePrepareBundle(p.market_id, p.ticket_id)
                                }
                              >
                                {preparingBundles.has(bundleKey) && (
                                  <svg className="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                                  </svg>
                                )}
                                {preparingBundles.has(bundleKey)
                                  ? "Preparing..."
                                  : "Prepare to claim"}
                              </button>
                            )
                          ) : null}
                          <Link
                            className="rounded-full bg-white/10 px-3 py-2 text-white hover:bg-white/20 sm:py-1"
                            href={`/events/${encodeURIComponent(p.market_id)}`}
                          >
                            View market
                          </Link>
                          {(p.proof_request_id ||
                            p.merkle_root ||
                            ["pending_resolution", "settled", "claimed"].includes(
                              normalizePositionStatus(p.status)
                            )) && (
                            <Link
                              className="rounded-full bg-white/10 px-3 py-2 text-white hover:bg-white/20 sm:py-1"
                              href={
                                p.merkle_root
                                  ? `/proofs?eventId=${encodeURIComponent(p.market_id)}`
                                  : p.proof_request_id
                                  ? `/proofs?requestId=${encodeURIComponent(p.proof_request_id)}`
                                  : "/proofs"
                              }
                            >
                              View proofs
                            </Link>
                          )}
                          {p.tx_hash && txHref ? (
                            <a
                              className="rounded-full bg-white/10 px-3 py-2 text-white hover:bg-white/20 sm:py-1"
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
              );
            }
          )}
          {claimMessage && (
            <p className="text-sm text-emerald-200">
              {claimMessage}
              {claimTxHash ? (
                <>
                  {" "}
                  {txHref(claimTxHash) ? (
                    <a
                      className="underline underline-offset-4"
                      href={txHref(claimTxHash) ?? undefined}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {shortenHash(claimTxHash)}
                    </a>
                  ) : (
                    shortenHash(claimTxHash)
                  )}
                </>
              ) : null}
            </p>
          )}
          {claimError && (
            <p className="text-sm text-rose-200">
              {claimError instanceof Error
                ? claimError.message
                : String(claimError)}
            </p>
          )}
          {visibleCount < filteredPositions.length && (
            <div className="flex justify-center pt-2">
              <button
                type="button"
                onClick={() => setVisibleCount((prev) => prev + PAGE_SIZE)}
                className="rounded-full border border-white/15 bg-white/5 px-6 py-2 text-xs font-semibold uppercase tracking-wide text-slate-300 transition hover:bg-white/10 hover:text-white"
              >
                Load more ({filteredPositions.length - visibleCount} remaining)
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
