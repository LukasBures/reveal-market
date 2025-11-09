import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HeartbeatBadge } from "@/components/metrics/HeartbeatBadge";
import { fetchHealthSnapshot } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  fetchHealthSnapshot: vi.fn(),
}));

describe("HeartbeatBadge", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns null when no heartbeat is available", async () => {
    (fetchHealthSnapshot as vi.Mock).mockResolvedValue(null);
    const element = await HeartbeatBadge();
    expect(element).toBeNull();
  });

  it("renders the latest heartbeat timestamp and latency", async () => {
    (fetchHealthSnapshot as vi.Mock).mockResolvedValue({
      status: "ok",
      workerHeartbeat: {
        marketsProcessed: 32,
        latencyMs: 42.4,
        timestamp: "2024-05-01T12:00:00.000Z",
      },
    });
    const localeSpy = vi.spyOn(Date.prototype, "toLocaleString").mockReturnValue("May 1, 2024");

    const element = await HeartbeatBadge();
    render(element!);

    expect(screen.getByText(/Last sync/i)).toBeInTheDocument();
    expect(screen.getByText("May 1, 2024")).toBeInTheDocument();
    expect(screen.getByText("(42 ms)")).toBeInTheDocument();

    localeSpy.mockRestore();
  });
});
