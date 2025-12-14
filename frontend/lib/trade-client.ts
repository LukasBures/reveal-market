import { DEFAULT_API_BASE } from "./api";

export async function submitClaim(marketId: string, wallet: string, ticketId?: number | null) {
  const res = await fetch(`${DEFAULT_API_BASE}/trade/claim`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      market_id: marketId,
      wallet_address: wallet,
      ticket_id: ticketId ?? null,
    }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Claim failed (${res.status}): ${detail}`);
  }
  return res.json() as Promise<{ tx_hash: string; status: string }>;
}
