import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProofsClient } from "@/components/proofs/ProofsClient";
import type { ProofReceipt } from "@/lib/api";
import { fetchProofReceipts } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchProofReceipts: vi.fn(),
  };
});

const baseReceipt: ProofReceipt = {
  proofNonce: "0xabc",
  verifier: "0xVerifier",
  marketAddress: "0xMarket",
  transactionHash: "0xTxHash",
  verifiedAt: "2025-01-01T00:00:00.000Z",
  status: "verified",
  zkVerifyReceipt: null,
  circuitVersion: 1,
  outcomeHash: "0xoutcome",
  winningPool: "100000000",
  totalPool: "200000000",
};

describe("ProofsClient", () => {
  const mockFetch = vi.mocked(fetchProofReceipts);

  beforeEach(() => {
    mockFetch.mockReset();
    class NoopIntersectionObserver {
      constructor() {}
      observe() {}
      disconnect() {}
      unobserve() {}
      takeRecords() {
        return [];
      }
    }
    (globalThis as any).IntersectionObserver = NoopIntersectionObserver;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders provided receipts and the manual pagination control", () => {
    render(<ProofsClient initialReceipts={[baseReceipt]} pageSize={1} />);

    expect(screen.getByText(/Proof nonce/i)).toBeInTheDocument();
    expect(screen.getByText(/Load more receipts/i)).toBeInTheDocument();
  });

  it("fetches and appends additional receipts when the button is clicked", async () => {
    const nextReceipt: ProofReceipt = {
      ...baseReceipt,
      proofNonce: "0xdef",
      marketAddress: "0xAnother",
      transactionHash: "0xNewTx",
    };
    mockFetch.mockResolvedValueOnce([nextReceipt]);

    render(<ProofsClient initialReceipts={[baseReceipt]} pageSize={1} />);

    fireEvent.click(screen.getByRole("button", { name: /load more receipts/i }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(1, { offset: 1 });
      expect(screen.getByText(/0xdef/i)).toBeInTheDocument();
    });
  });

  it("stops paginating when the API returns no additional data", async () => {
    mockFetch.mockResolvedValueOnce([]);

    render(<ProofsClient initialReceipts={[baseReceipt]} pageSize={1} />);

    fireEvent.click(screen.getByRole("button", { name: /load more receipts/i }));

    await waitFor(() => {
      expect(screen.getByText(/All available proof receipts/i)).toBeInTheDocument();
    });
  });
});
