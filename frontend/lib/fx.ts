export const formatZenUsd = (zenUsd: number | null | undefined, decimals = 4): string | null => {
  if (typeof zenUsd !== "number" || Number.isNaN(zenUsd)) {
    return null;
  }
  return zenUsd.toFixed(decimals);
};

// Legacy alias for earlier ETH naming.
export const formatEthUsd = formatZenUsd;
