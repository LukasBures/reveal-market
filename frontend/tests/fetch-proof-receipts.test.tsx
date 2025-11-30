import { describe, beforeEach, afterEach, it, expect, vi } from "vitest";
import { fetchProofReceipts } from "@/lib/api";

describe("fetchProofReceipts", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        {
          requestId: "req-1",
          marketId: 1,
          conditionId: "0xabc",
          marketAddress: "0xdef",
          generatedAt: "2024-01-01T00:00:00Z",
          proofHash: "0xbeef",
          circuitHash: "0xcafe",
          publicSignals: ["0xroot", "1", "0", "10", "20", "50", "5", "5", "0xcafe"],
          winningPool: "10",
          totalPool: "20",
        },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds the request using limit and offset", async () => {
    const result = await fetchProofReceipts(12, { offset: 24 });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/proofs?limit=12&offset=24"),
      expect.objectContaining({
        next: expect.any(Object),
      }),
    );
    expect(result.receipts).toHaveLength(1);
    expect(result.error).toBeUndefined();
  });

  it("returns an empty set with an error message if the fetch fails", async () => {
    fetchMock.mockRejectedValueOnce(new Error("connect refused"));
    const result = await fetchProofReceipts(5);
    expect(result.receipts).toEqual([]);
    expect(result.error).toContain("connect");
  });
});
