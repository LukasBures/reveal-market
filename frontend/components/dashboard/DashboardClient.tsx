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
import { fetchPositions, fetchClaimBundles, fetchClaimStatus } from "@/lib/api";
import type { ClaimBundle, PositionRecord } from "@/lib/api-types";
import { defaultChain } from "@/lib/wagmi";
import { RELAYER_ESCROW_ADDRESS, ZEN_TOKEN_ADDRESS } from "@/lib/tokens";
import { formatDateTime, normalizeTxHash } from "@/lib/formatters";
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
    description: "Oracle & Proof",
  },
  { key: "settled", label: "Settled", description: "Payout path ready" },
  { key: "claimed", label: "Claimed", description: "Payout received" },
] as const;

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
            ? "Awaiting proof"
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
                  <span className="text-[11px] uppercase tracking-[0.2em]">
                    {stage.label}
                  </span>
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
      <p className="mt-2 text-[11px] text-slate-400">
        {isCancelled
          ? `Market cancelled${clippedReason ? ` — ${clippedReason}` : ""}.`
          : isFinal
          ? claimable
            ? "All phases cleared — claim is open."
            : "All phases cleared."
          : awaitingProof
          ? "Resolution set — proof in progress."
          : `Arrows pulse toward ${nextLabel}.`}
      </p>
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
    let ticketIdValue = 0n;
    let outcomeIdValue = 0n;
    let amountValue = 0n;
    let payoutValue = 0n;
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
          idx & 1n
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
      ? (normalizedEscrow / 1e18).toFixed(3)
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
        normalizeWei((p as any).payout_wei) ??
        normalizeWei((p as any).potential_payout_wei);
      const bundlePayoutWei = bundle
        ? normalizeWei((bundle as any).payoutWei ?? bundle.amountWei)
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
      <div className="rounded-3xl border border-white/10 bg-slate-950/60 p-4">
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
          Escrow
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-white">
          <span>
            Balance: {escrowDisplay} ZEN{" "}
            {ZEN_TOKEN_ADDRESS ? "" : "(ZEN token missing)"}
          </span>
          <span className="break-all text-slate-400">
            Escrow: {RELAYER_ESCROW_ADDRESS ?? "n/a"} | Chain:{" "}
            {chainMismatch ? "Wrong network" : defaultChain.name}
          </span>
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <div className="rounded-2xl border border-white/10 bg-gradient-to-br from-emerald-900/40 via-black/60 to-black/80 p-4 shadow-inner shadow-emerald-900/30">
            <div className="flex items-center justify-between text-slate-300">
              <p className="text-xs uppercase tracking-[0.2em] text-emerald-200">
                Deposit
              </p>
              <span className="text-[11px] text-slate-400">
                Wallet:{" "}
                {tokenBalance !== undefined && tokenBalance !== null
                  ? `${(Number(tokenBalance) / 1e18).toFixed(3)} ZEN`
                  : "—"}
              </span>
            </div>
            <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
              <input
                type="number"
                name="escrowDepositAmount"
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
                className="w-full whitespace-nowrap rounded-full bg-emerald-500 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-white shadow-lg shadow-emerald-900/50 transition hover:-translate-y-[1px] hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-emerald-800/60 sm:w-auto"
                disabled={Boolean(fundingBlockedReason)}
                title={depositCtaTitle}
              >
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
          <div className="rounded-2xl border border-white/10 bg-gradient-to-br from-slate-800/40 via-black/60 to-black/80 p-4 shadow-inner shadow-black/40">
            <div className="flex items-center justify-between text-slate-300">
              <p className="text-xs uppercase tracking-[0.2em] text-slate-200">
                Withdraw
              </p>
              <span className="text-[11px] text-slate-400">
                Escrow:{" "}
                {normalizedOnchainEscrow !== null &&
                Number.isFinite(normalizedOnchainEscrow)
                  ? `${(normalizedOnchainEscrow / 1e18).toFixed(3)} ZEN`
                  : "—"}
              </span>
            </div>
            <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
              <input
                type="number"
                name="escrowWithdrawAmount"
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
                className="w-full whitespace-nowrap rounded-full bg-white/15 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-white shadow-lg shadow-black/50 transition hover:-translate-y-[1px] hover:bg-white/25 disabled:cursor-not-allowed disabled:bg-white/10 sm:w-auto"
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
      ) : positionsLoading || loading ? (
        <div className="rounded-3xl border border-white/10 bg-slate-950/60 p-6 text-slate-200">
          Loading positions...
        </div>
      ) : positions.length === 0 ? (
        <div className="rounded-3xl border border-white/10 bg-slate-950/60 p-6 text-slate-200">
          No positions yet.
        </div>
      ) : (
        <div className="space-y-4">
          {bundleError && (
            <div className="rounded-2xl border border-amber-400/40 bg-amber-500/10 p-3 text-amber-100">
              {bundleError}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-white/10 bg-gradient-to-r from-slate-900/70 via-slate-900/40 to-slate-800/40 px-4 py-3 shadow-inner shadow-black/30">
            <input
              type="search"
              name="positionsSearch"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search markets"
              className="min-w-[200px] flex-1 rounded-lg border border-white/20 bg-black/30 px-3 py-2 text-sm text-white shadow-inner shadow-black/40 focus:border-white/60 focus:outline-none"
            />
            <div className="flex flex-wrap items-center gap-2">
              {(["all", "open", "settled", "claimable"] as const).map(
                (filter) => (
                  <button
                    key={filter}
                    type="button"
                    onClick={() => setStatusFilter(filter)}
                    className={clsx(
                      "rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide transition",
                      statusFilter === filter
                        ? "bg-white/80 text-black shadow"
                        : "bg-white/10 text-white hover:bg-white/20"
                    )}
                  >
                    {filter}
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
                  className="appearance-none rounded-full border border-white/20 bg-white/10 px-3 py-1 pr-8 text-xs font-semibold uppercase tracking-wide text-white shadow shadow-black/30 transition focus:border-white/60 focus:outline-none"
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
          <div className="grid gap-3 rounded-2xl border border-white/10 bg-gradient-to-r from-indigo-900/30 via-slate-900/60 to-slate-900/40 p-4 text-white shadow-inner shadow-black/30 sm:grid-cols-4">
            <div className="rounded-xl border border-white/10 bg-white/5 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-300">
                Deposited in escrow
              </p>
              <p className="mt-1 text-2xl font-semibold text-white">
                {totalEscrowZen !== null && Number.isFinite(totalEscrowZen)
                  ? `${totalEscrowZen.toFixed(3)} ZEN`
                  : "—"}
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/5 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-300">
                Total staked
              </p>
              <p className="mt-1 text-2xl font-semibold text-white">
                {totalStakeZen.toFixed(3)} ZEN
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/5 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-300">
                Total to win
              </p>
              <p className="mt-1 text-2xl font-semibold text-white">
                {totalToWinZen > 0 ? `${totalToWinZen.toFixed(3)} ZEN` : "—"}
              </p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/5 p-3">
              <p className="text-[11px] uppercase tracking-[0.25em] text-slate-300">
                PnL / ROI
              </p>
              <p className="mt-1 text-2xl font-semibold text-white">
                {Number.isFinite(pnlZen)
                  ? `${pnlZen >= 0 ? "+" : ""}${pnlZen.toFixed(3)} ZEN`
                  : "—"}
              </p>
              <p className="text-xs text-slate-400">
                {roi !== null ? `${(roi * 100).toFixed(1)}%` : "—"}
              </p>
            </div>
          </div>
          {filteredPositions.map(
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
                  className="rounded-2xl border border-white/10 bg-black/40 p-4 shadow-lg shadow-black/30"
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
                              {highlightMode === "none" ? (
                                <span className="ml-2 inline-flex rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-300">
                                  Lost
                                </span>
                              ) : null}
                            </p>
                          </div>
                          <div className="text-right">
                            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
                              Stake
                            </p>
                            <p className="font-mono text-white">
                              {p.stake_zen.toFixed(3)} ZEN
                            </p>
                          </div>
                          <div className="text-right">
                            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
                              To win
                            </p>
                            <p className="font-mono text-white">
                              {toWinZen !== null
                                ? `${toWinZen.toFixed(3)} ZEN`
                                : p.claimable
                                ? "Get payment data"
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
                          <span>
                            Merkle root:{" "}
                            {p.merkle_root
                              ? `${p.merkle_root.slice(
                                  0,
                                  8
                                )}...${p.merkle_root.slice(-6)}`
                              : "—"}
                          </span>
                        </div>
                        <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-200">
                          {p.status === "settled" && p.claimable ? (
                            bundle ? (
                              <button
                                type="button"
                                className="rounded-full bg-emerald-500 px-3 py-1 font-semibold text-white hover:bg-emerald-400 disabled:cursor-not-allowed"
                                disabled={
                                  chainMismatch ||
                                  claimingTickets.has(bundleKey)
                                }
                                onClick={() =>
                                  handleClaim(p.market_id, p.ticket_id)
                                }
                              >
                                {claimingTickets.has(bundleKey)
                                  ? "Claiming..."
                                  : "Claim"}
                              </button>
                            ) : (
                              <button
                                type="button"
                                className="rounded-full bg-emerald-500 px-3 py-1 font-semibold text-white hover:bg-emerald-400 disabled:cursor-not-allowed"
                                disabled={
                                  chainMismatch ||
                                  preparingBundles.has(bundleKey)
                                }
                                onClick={() =>
                                  handlePrepareBundle(p.market_id, p.ticket_id)
                                }
                              >
                                {preparingBundles.has(bundleKey)
                                  ? "Preparing..."
                                  : "Get payment data"}
                              </button>
                            )
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
                              p.merkle_root
                                ? `/proofs?eventId=${encodeURIComponent(
                                    p.market_id
                                  )}`
                                : p.proof_request_id
                                ? `/proofs?requestId=${encodeURIComponent(
                                    p.proof_request_id
                                  )}`
                                : "/proofs"
                            }
                          >
                            View proofs
                          </Link>
                          {p.tx_hash && txHref ? (
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
        </div>
      )}
    </div>
  );
}
