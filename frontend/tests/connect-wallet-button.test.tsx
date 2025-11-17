import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  reset: () => void;
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
  }) as unknown as Connector;

const walletConnectConnector = createConnector("walletConnect", "WalletConnect");
const metaMaskConnector = createConnector("metaMaskSDK", "MetaMask");

let currentAccountState: WagmiAccountState;
let currentConnectState: WagmiConnectState;
let currentDisconnectState: WagmiDisconnectState;

vi.mock("wagmi", () => ({
  useAccount: () => currentAccountState,
  useConnect: () => currentConnectState,
  useDisconnect: () => currentDisconnectState,
}));

describe("ConnectWalletButton", () => {
  beforeEach(() => {
    currentAccountState = {
      address: undefined,
      status: "disconnected",
    };
    currentConnectState = {
      connect: vi.fn(),
      connectors: [walletConnectConnector, metaMaskConnector],
      status: "idle",
      error: null,
      reset: vi.fn(),
    };
    currentDisconnectState = {
      disconnect: vi.fn(),
    };
    vi.clearAllMocks();
    delete (window as typeof window & { ethereum?: unknown }).ethereum;
  });

  it("opens the modal and triggers connect for an available wallet", async () => {
    render(<ConnectWalletButton />);

    fireEvent.click(screen.getByRole("button", { name: /connect wallet/i }));
    const walletButton = await screen.findByRole("button", { name: /walletconnect/i });
    fireEvent.click(walletButton);

    expect(currentConnectState.connect).toHaveBeenCalledWith({ connector: walletConnectConnector });
  });

  it("omits MetaMask when no injected provider exists", () => {
    render(<ConnectWalletButton />);
    fireEvent.click(screen.getByRole("button", { name: /connect wallet/i }));
    expect(screen.queryByText("MetaMask")).not.toBeInTheDocument();
  });

  it("shows MetaMask when an injected provider is detected", async () => {
    Object.defineProperty(window, "ethereum", {
      configurable: true,
      value: { providers: [{ isMetaMask: true }] },
    });

    render(<ConnectWalletButton />);
    fireEvent.click(screen.getByRole("button", { name: /connect wallet/i }));

    await waitFor(() => expect(screen.getByText("MetaMask")).toBeInTheDocument());
  });

  it("shows the connected address and allows disconnecting", async () => {
    currentAccountState = {
      address: "0x1234567890abcdef1234567890abcdef12345678",
      status: "reconnecting",
    };

    render(<ConnectWalletButton />);

    const triggerButton = screen.getByRole("button", { name: /0x1234…5678/i });
    expect(triggerButton).toBeInTheDocument();

    fireEvent.click(triggerButton);
    const disconnectButton = screen.getByRole("button", { name: /disconnect/i });
    fireEvent.click(disconnectButton);

    expect(currentDisconnectState.disconnect).toHaveBeenCalledTimes(1);
  });
});
