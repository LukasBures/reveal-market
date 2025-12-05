export const formatZenUsd = (zenUsd: number | null | undefined, decimals = 4): string | null => {
  if (typeof zenUsd !== "number" || Number.isNaN(zenUsd)) {
    return null;
  }
  const fixed = zenUsd.toFixed(decimals);
  const trimmed = fixed.replace(/\.?0+$/, "");
  return trimmed.length ? trimmed : fixed;
};

// Legacy alias for earlier ETH naming.
export const formatEthUsd = formatZenUsd;
