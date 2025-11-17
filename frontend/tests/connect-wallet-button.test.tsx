import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Connector } from "wagmi";
import { ConnectWalletButton } from "@/components/wallet/ConnectWalletButton";

type WagmiAccountState = {
  address?: `0x${string}` | undefined;
  status: "connected" | "connecting" | "disconnected" | "reconnecting";
};

type WagmiConnectState = {
  connect: (args: { connector: Connector }) => void;
  connectors: Connector[];
  status: "idle" | "pending" | "success" | "error";
  error: Error | null;
};

type WagmiDisconnectState = {
  disconnect: () => void;
};

const createConnector = (id: string, name: string): Connector =>
  ({
    id,
    name,
    uid: `${id}-uid`,
    type: "app",
    ready: true,
  }) as unknown as Connector;

const walletConnectConnector = createConnector("walletConnect", "WalletConnect");

let currentAccountState: WagmiAccountState;
let currentConnectState: WagmiConnectState;
let currentDisconnectState: WagmiDisconnectState;

vi.mock("wagmi", async () => {
  const actual = await vi.importActual<typeof import("wagmi")>("wagmi");
  return {
    ...actual,
    useAccount: () => currentAccountState,
    useConnect: () => currentConnectState,
    useDisconnect: () => currentDisconnectState,
  };
});

describe("ConnectWalletButton", () => {
  beforeEach(() => {
    currentAccountState = {
      address: undefined,
      status: "disconnected",
    };
    currentConnectState = {
      connect: vi.fn(),
      connectors: [walletConnectConnector],
      status: "idle",
      error: null,
    };
    currentDisconnectState = {
      disconnect: vi.fn(),
    };
    vi.clearAllMocks();
  });

  it("connects with the first connector when clicked", () => {
    render(<ConnectWalletButton />);

    const button = screen.getByRole("button", { name: /connect wallet/i });
    fireEvent.click(button);

    expect(currentConnectState.connect).toHaveBeenCalledWith({ connector: walletConnectConnector });
  });

  it("shows the connected address and disconnect button", () => {
    currentAccountState = {
      address: "0x1234567890abcdef1234567890abcdef12345678",
      status: "connected",
    };

    render(<ConnectWalletButton />);

    expect(screen.getByText("0x1234…5678")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /disconnect/i }));
    expect(currentDisconnectState.disconnect).toHaveBeenCalledTimes(1);
  });

  it("disables the button when no connector exists", () => {
    currentConnectState.connectors = [];

    render(<ConnectWalletButton />);
    const button = screen.getByRole("button", { name: /connect wallet/i });

    expect(button).toBeDisabled();
  });
});
