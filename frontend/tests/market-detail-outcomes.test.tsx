import { render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { MarketDetailOutcomes } from "@/components/markets/MarketDetailOutcomes";
import type { MarketDetail } from "@/lib/api-types";

const baseDetail: MarketDetail = {
  eventId: "evt-detail",
  title: "Detail",
  category: "General",
  outcomes: ["Yes", "No"],
  outcomePrices: [0.6, 0.4],
};

vi.mock("@/lib/wagmi", () => ({
  defaultChain: { id: 2651420, name: "Horizen Testnet" },
}));

vi.mock("wagmi", () => ({
  useConnection: () => ({ address: undefined, connector: undefined, status: "disconnected" }),
  useChainId: () => 2651420,
  useSwitchChain: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, error: null }),
  useReadContract: () => ({ data: undefined, isFetching: false, refetch: vi.fn() }),
  useWriteContract: () => ({ mutateAsync: vi.fn(), error: null }),
  usePublicClient: () => undefined,
}));

class EventSourceMock {
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(_url: string) {}
  close() {}
}

class WebSocketMock {
  static instances: WebSocketMock[] = [];
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(_url: string) {
    WebSocketMock.instances.push(this);
  }
  close() {
    this.onclose?.();
  }
}

beforeAll(() => {
  global.EventSource = EventSourceMock as unknown as typeof EventSource;
  global.WebSocket = WebSocketMock as unknown as typeof WebSocket;
});

beforeEach(() => {
  WebSocketMock.instances = [];
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ zen_usd: 10, raw_zen_usd: 10.3, stale: false }),
  }) as unknown as typeof fetch;
});

describe("MarketDetailOutcomes", () => {
  it("renders an informative empty state when no outcomes exist", () => {
    render(<MarketDetailOutcomes market={{ ...baseDetail, outcomes: [] }} />);
    expect(screen.getByText(/no outcome data available/i)).toBeInTheDocument();
  });

  it("shows each outcome with its probability", () => {
    render(<MarketDetailOutcomes market={baseDetail} />);
    expect(screen.getAllByText("Yes")[0]).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
    expect(screen.getAllByText("No")[0]).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
  });

  it("provides buy links for each outcome", () => {
    render(<MarketDetailOutcomes market={baseDetail} />);
    expect(screen.getByRole("link", { name: /buy yes/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /buy no/i })).toBeInTheDocument();
  });
});
