import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProofsPage from "@/app/proofs/page";

const fetchProofReceiptsMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({
  fetchProofReceipts: fetchProofReceiptsMock,
}));

const proofsClientMock = vi.hoisted(() => vi.fn(() => <div data-testid="proofs-client" />));

vi.mock("@/components/proofs/ProofsClient", () => ({
  ProofsClient: proofsClientMock,
}));

vi.mock("next/dynamic", () => ({
  __esModule: true,
  default: () => proofsClientMock,
}));

describe("ProofsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the proofs client when receipts are loaded", async () => {
    fetchProofReceiptsMock.mockResolvedValue({ receipts: [{ eventId: "evt-1" }], error: undefined });
    const ui = await ProofsPage();
    render(ui);
    expect(proofsClientMock).toHaveBeenCalledWith(
      expect.objectContaining({ initialReceipts: [{ eventId: "evt-1" }] }),
      expect.anything(),
    );
    expect(screen.queryByText(/Unable to load proof receipts/i)).toBeNull();
  });

  it("shows an error notice when the API call fails", async () => {
    fetchProofReceiptsMock.mockResolvedValue({ receipts: [], error: "Not Found" });
    const ui = await ProofsPage();
    render(ui);
    expect(screen.getByText(/Unable to load proof receipts/i)).toBeInTheDocument();
    expect(screen.getByText(/Not Found/)).toBeInTheDocument();
    expect(proofsClientMock).not.toHaveBeenCalled();
  });
});
