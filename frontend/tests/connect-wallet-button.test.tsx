import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Connector } from "wagmi";
import { ConnectWalletButton } from "@/components/wallet/ConnectWalletButton";

type WagmiAccountState = {
  address?: `0x${string}` | undefined;
  chain?: { id: number; name: string };
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

type WagmiSignMessageState = {
  data?: `0x${string}` | undefined;
  error: Error | null;
  isPending: boolean;
  signMessageAsync: (args: { message: string }) => Promise<string>;
};

type WagmiSwitchChainState = {
  chains: { id: number; name: string }[];
  error: Error | null;
  isPending: boolean;
  switchChain?: (args: { chainId: number }) => void;
};

const createConnector = (id: string, name: string): Connector =>
  ({
    id,
    name,
    uid: `${id}-uid`,
    type: "app",
    ready: true,
  }) as unknown as Connector;

const metaMaskConnector = createConnector("metaMask", "MetaMask");
const injectedConnector = createConnector("injected", "Injected");
const coinbaseConnector = createConnector("coinbaseWalletSDK", "Coinbase Wallet");
const walletConnectConnector = createConnector("walletConnect", "WalletConnect");
const hoistedDefaults = vi.hoisted(() => ({
  defaultChain: { id: 2651420, name: "Horizen Testnet" } as const,
}));

let currentAccountState: WagmiAccountState;
let currentConnectState: WagmiConnectState;
let currentDisconnectState: WagmiDisconnectState;
let currentSignMessageState: WagmiSignMessageState;
let currentSwitchChainState: WagmiSwitchChainState;

vi.mock("wagmi", async () => {
  const actual = await vi.importActual<typeof import("wagmi")>("wagmi");
  return {
    ...actual,
    defaultChain: hoistedDefaults.defaultChain,
    useAccount: () => currentAccountState,
    useConnect: () => currentConnectState,
    useDisconnect: () => currentDisconnectState,
    useSignMessage: () => currentSignMessageState,
    useSwitchChain: () => currentSwitchChainState,
  };
});

vi.mock("@/lib/wagmi", () => ({
  defaultChain: hoistedDefaults.defaultChain,
}));

describe("ConnectWalletButton", () => {
  beforeEach(() => {
    currentAccountState = {
      address: undefined,
      status: "disconnected",
    };
    currentConnectState = {
      connect: vi.fn(),
      connectors: [metaMaskConnector, injectedConnector, coinbaseConnector, walletConnectConnector],
      status: "idle",
      error: null,
    };
    currentDisconnectState = {
      disconnect: vi.fn(),
    };
    currentSignMessageState = {
      data: undefined,
      error: null,
      isPending: false,
      signMessageAsync: vi.fn(async ({ message }: { message: string }) => `0xsigned-${message}`),
    };
    currentSwitchChainState = {
      chains: [hoistedDefaults.defaultChain],
      error: null,
      isPending: false,
      switchChain: vi.fn(),
    };
    vi.clearAllMocks();
  });

  it("opens the modal, enforces the terms acknowledgement, and connects with the selected wallet", () => {
    render(<ConnectWalletButton />);

    fireEvent.click(screen.getByRole("button", { name: /connect wallet/i }));

    const walletConnectButton = screen.getByRole("button", { name: /^walletconnect/i });
    expect(screen.getByRole("button", { name: /metamask/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /rabby/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /coinbase wallet/i })).toBeInTheDocument();

    fireEvent.click(walletConnectButton);
    const checkbox = screen.getByRole("checkbox", { name: /i have read/i });
    let connectCta = screen.getByRole("button", { name: /connect with walletconnect/i });
    expect(connectCta).toBeDisabled();

    fireEvent.click(checkbox);
    connectCta = screen.getByRole("button", { name: /connect with walletconnect/i });
    fireEvent.click(connectCta);

    expect(currentConnectState.connect).toHaveBeenCalledWith({ connector: walletConnectConnector });
  });

  it("allows managing a connected session inside the modal", () => {
    currentAccountState = {
      address: "0x1234567890abcdef1234567890abcdef12345678",
      chain: { id: 1, name: "Other Chain" },
      status: "connected",
    };

    render(<ConnectWalletButton />);

    expect(screen.getByRole("button", { name: /0x1234…5678/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /0x1234…5678/i }));
    fireEvent.click(screen.getByRole("button", { name: /disconnect/i }));
    expect(currentDisconnectState.disconnect).toHaveBeenCalledTimes(1);

    const switchButton = screen.getByRole("button", {
      name: new RegExp(`switch to ${hoistedDefaults.defaultChain.name}`, "i"),
    });
    fireEvent.click(switchButton);
    expect(currentSwitchChainState.switchChain).toHaveBeenCalledWith({ chainId: hoistedDefaults.defaultChain.id });

    expect(screen.queryByRole("button", { name: /sign message/i })).not.toBeInTheDocument();
  });

  it("renders a fallback when no connectors are available", () => {
    currentConnectState.connectors = [];

    render(<ConnectWalletButton />);
    fireEvent.click(screen.getByRole("button", { name: /connect wallet/i }));

    expect(screen.getByText(/no compatible wallets detected/i)).toBeInTheDocument();
  });

  it("omits signing controls when connected", () => {
    currentAccountState = {
      address: "0x9999999999999999999999999999999999999999",
      chain: hoistedDefaults.defaultChain,
      status: "connected",
    };

    render(<ConnectWalletButton />);
    fireEvent.click(screen.getByRole("button", { name: /0x9999/i }));

    expect(screen.queryByPlaceholderText(/enter a message/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sign message/i })).not.toBeInTheDocument();
  });

  it("hides switch action when switchChain is unavailable", () => {
    currentAccountState = {
      address: "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
      chain: { id: 1, name: "Other Chain" },
      status: "connected",
    };
    currentSwitchChainState.switchChain = undefined;

    render(<ConnectWalletButton />);
    fireEvent.click(screen.getByRole("button", { name: /0xabcd/i }));

    expect(
      screen.queryByRole("button", { name: new RegExp(`switch to ${hoistedDefaults.defaultChain.name}`, "i") }),
    ).not.toBeInTheDocument();
  });
});
