import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ZENRISE_JOURNEY_COMPLETE_EVENT_NAME,
  ZENRISE_JOURNEY_EVENT_NAME,
  ZENRISE_JOURNEY_STORAGE_KEY,
  captureZenriseAttribution,
  readZenriseJourney,
  recordZenriseMarketInspection,
  recordZenriseWalletConnected,
  type ZenriseJourneyEventDetail,
} from "@/lib/zenriseJourney";

const isZenriseJourneyEventDetail = (value: unknown): value is ZenriseJourneyEventDetail => {
  return (
    typeof value === "object" &&
    value !== null &&
    "type" in value &&
    "journey" in value
  );
};

describe("zenriseJourney", () => {
  const originalTarget = process.env.NEXT_PUBLIC_ZENRISE_MARKET_INSPECTION_TARGET;

  beforeEach(() => {
    window.localStorage.removeItem(ZENRISE_JOURNEY_STORAGE_KEY);
    process.env.NEXT_PUBLIC_ZENRISE_MARKET_INSPECTION_TARGET = "2";
    window.history.replaceState(null, "", "/?zenrise_click_id=click-1&zenrise_task_id=task-1");
  });

  afterEach(() => {
    window.localStorage.removeItem(ZENRISE_JOURNEY_STORAGE_KEY);
    if (originalTarget === undefined) {
      delete process.env.NEXT_PUBLIC_ZENRISE_MARKET_INSPECTION_TARGET;
    } else {
      process.env.NEXT_PUBLIC_ZENRISE_MARKET_INSPECTION_TARGET = originalTarget;
    }
    vi.restoreAllMocks();
  });

  it("captures first-party attribution params without sending network traffic", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    const journey = captureZenriseAttribution();

    expect(journey?.attribution?.params.zenrise_click_id).toBe("click-1");
    expect(journey?.attribution?.params.zenrise_task_id).toBe("task-1");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("records wallet connection and counts only connected-wallet market inspections", () => {
    recordZenriseMarketInspection({
      walletAddress: "0xabc",
      eventId: "market-before-wallet",
      title: "Before wallet",
    });
    expect(readZenriseJourney()).toBeNull();

    recordZenriseWalletConnected({
      address: "0xAbC",
      chainId: 26514,
      connectorId: "metaMask",
      connectorName: "MetaMask",
    });

    const first = recordZenriseMarketInspection({
      walletAddress: "0xabc",
      eventId: "market-1",
      canonicalEventId: "event-1",
      title: "Market 1",
    });
    const second = recordZenriseMarketInspection({
      walletAddress: "0xabc",
      eventId: "market-1",
      canonicalEventId: "event-1",
      title: "Market 1",
    });

    expect(first?.uniqueMarketCount).toBe(1);
    expect(second?.uniqueMarketCount).toBe(1);
    expect(second?.inspectedMarkets[0]?.views).toBe(2);
    expect(second?.wallet?.address).toBe("0xabc");
  });

  it("emits completion when the configured unique market target is reached", () => {
    const events: ZenriseJourneyEventDetail[] = [];
    const completed: ZenriseJourneyEventDetail[] = [];
    window.addEventListener(ZENRISE_JOURNEY_EVENT_NAME, (event) => {
      if (event instanceof CustomEvent && isZenriseJourneyEventDetail(event.detail)) {
        events.push(event.detail);
      }
    });
    window.addEventListener(ZENRISE_JOURNEY_COMPLETE_EVENT_NAME, (event) => {
      if (event instanceof CustomEvent && isZenriseJourneyEventDetail(event.detail)) {
        completed.push(event.detail);
      }
    });

    recordZenriseWalletConnected({ address: "0xabc" });
    recordZenriseMarketInspection({ walletAddress: "0xabc", eventId: "market-1", title: "Market 1" });
    const journey = recordZenriseMarketInspection({
      walletAddress: "0xabc",
      eventId: "market-2",
      title: "Market 2",
    });

    expect(journey?.done).toBe(true);
    expect(journey?.uniqueMarketCount).toBe(2);
    expect(completed).toHaveLength(1);
    expect(completed[0]?.journey.done).toBe(true);
    expect(events.map((event) => event.type)).toContain("completed");
  });
});
