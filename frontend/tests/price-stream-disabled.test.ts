import { describe, expect, it, vi } from "vitest";
import { seedHistory, seedInitialOutcomes } from "@/hooks/usePriceStreamConnection";

const createMarketWebSocketMock = vi.hoisted(() => vi.fn());
const createMarketStreamMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/pricing-client", () => ({
  priceStreamsDisabled: true,
  shouldUseStreamerWs: () => true,
  createMarketWebSocket: createMarketWebSocketMock,
  createMarketStream: createMarketStreamMock,
}));

describe("price streams disabled", () => {
  it("does not open connections when seeding history", () => {
    seedHistory("m-disabled", 0, [
      { timestamp: "t1", price: 0.5, display_price: 0.5 },
    ]);
    expect(createMarketWebSocketMock).not.toHaveBeenCalled();
    expect(createMarketStreamMock).not.toHaveBeenCalled();
  });

  it("does not open connections when seeding initial outcomes", () => {
    seedInitialOutcomes("m-disabled", [0.4, 0.6]);
    expect(createMarketWebSocketMock).not.toHaveBeenCalled();
    expect(createMarketStreamMock).not.toHaveBeenCalled();
  });
});
