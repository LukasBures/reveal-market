import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PriceBanner } from "@/components/layout/PriceBanner";

const hoisted = vi.hoisted(() => ({
  defaultChain: { id: 999, name: "Test Chain" },
}));

type AccountState = {
  chain?: { id: number };
  connector?: { switchChain?: () => void } | undefined;
  status: "connected" | "disconnected" | "connecting" | "reconnecting";
};

let accountState: AccountState;
let switchChainMock: ReturnType<typeof vi.fn>;

vi.mock("wagmi", () => ({
  useConnection: () => accountState,
  useSwitchChain: () => ({ mutate: switchChainMock, isPending: false }),
}));

vi.mock("@/lib/wagmi", () => ({
  defaultChain: hoisted.defaultChain,
}));

describe("PriceBanner", () => {
  beforeEach(() => {
    accountState = { status: "disconnected" };
    switchChainMock = vi.fn();
  });

  it("prompts a network switch when on the wrong chain", () => {
    accountState = { chain: { id: 1 }, connector: { switchChain: switchChainMock }, status: "connected" };

    render(<PriceBanner fxLabel="FX: 1 ZEN" fxError={null} fxStale={false} />);

    expect(screen.getByText(/wrong network/i)).toBeInTheDocument();
    const switchButton = screen.getByRole("button", { name: /switch to test chain/i });
    fireEvent.click(switchButton);
    expect(switchChainMock).toHaveBeenCalledWith({ chainId: hoisted.defaultChain.id });
  });

  it("surfaces FX stale and live labels when connected to the correct chain", () => {
    accountState = { chain: { id: hoisted.defaultChain.id }, status: "connected" };

    render(<PriceBanner fxLabel="FX: 1.2345" fxError={null} fxStale />);

    expect(screen.getByText(/fx stale/i)).toBeInTheDocument();
    expect(screen.getByText(/fx: 1\.2345/i)).toBeInTheDocument();
    expect(screen.queryByText(/live pricing/i)).not.toBeInTheDocument();
  });

  it("shows unavailable state and loading label when FX errors", () => {
    accountState = { status: "disconnected" };

    render(<PriceBanner fxLabel={null} fxError="timeout" fxStale={false} />);

    expect(screen.getByText(/fx unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/zen\/usd loading/i)).toBeInTheDocument();
    expect(screen.queryByText(/wrong network/i)).not.toBeInTheDocument();
  });

  it("surfaces API and streamer warnings when provided", () => {
    accountState = { chain: { id: hoisted.defaultChain.id }, status: "connected" };

    render(
      <PriceBanner
        fxLabel="FX: 1 ZEN"
        fxError={null}
        fxStale={false}
        apiWarning="API blocked"
        streamerWarning="Streamer blocked"
      />,
    );

    expect(screen.getByText(/api blocked/i)).toBeInTheDocument();
    expect(screen.getByText(/streamer blocked/i)).toBeInTheDocument();
    expect(screen.queryByText(/live pricing/i)).not.toBeInTheDocument();
  });
});
