import { render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LiveFxBadge } from "@/components/markets/LiveFxBadge";

const useFxStreamMock = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/useFxStream", () => ({
  useFxStream: useFxStreamMock,
}));

describe("LiveFxBadge", () => {
  beforeEach(() => {
    useFxStreamMock.mockReset();
  });

  it("renders live FX label with formatted rate", () => {
    useFxStreamMock.mockReturnValue({
      fx: { zen_usd: 1.2345, stale: false },
      status: "live",
    });

    render(<LiveFxBadge />);

    expect(screen.getByText(/fx live 1 zen = 1\.2345 usd/i)).toBeInTheDocument();
    expect(screen.getByText(/live via streamer/i)).toBeInTheDocument();
  });

  it("shows stale state when stream reports staleness", () => {
    useFxStreamMock.mockReturnValue({
      fx: { zen_usd: 1.2, stale: true },
      status: "stale",
    });

    render(<LiveFxBadge />);

    expect(screen.getByText(/fx stale/i)).toBeInTheDocument();
  });

  it("shows unavailable state when stream errors", () => {
    useFxStreamMock.mockReturnValue({
      fx: null,
      status: "error",
    });

    render(<LiveFxBadge />);

    expect(screen.getByText(/fx unavailable/i)).toBeInTheDocument();
  });
});
