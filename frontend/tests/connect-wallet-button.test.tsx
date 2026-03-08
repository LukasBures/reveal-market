import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Connector } from "wagmi";
import { ConnectWalletButton } from "@/components/wallet/ConnectWalletButton";

type WagmiAccountState = {
  address?: `0x${string}` | undefined;
  chain?: { id: number; name: string };
  connector?: Connector | undefined;
  status: "connected" | "connecting" | "disconnected" | "reconnecting";
};

type WagmiConnectState = {
  mutate: (args: { connector: Connector }) => void;
  status: "idle" | "pending" | "success" | "error";
  error: Error | null;
};

type WagmiDisconnectState = {
  mutate: () => void;
};

type WagmiSignMessageState = {
  data?: `0x${string}` | undefined;
  error: Error | null;
  isPending: boolean;
  mutateAsync: (args: { message: string }) => Promise<string>;
};

type WagmiSwitchChainState = {
  error: Error | null;
  isPending: boolean;
  mutate: (args: { chainId: number }) => void;
  mutateAsync?: (args: { chainId: number }) => Promise<void>;
};

const createConnector = (id: string, name: string, ready = true): Connector =>
  ({
    id,
    name,
    uid: `${id}-uid`,
    type: "app",
    ready,
  }) as unknown as Connector;

const metaMaskConnector = createConnector("metaMask", "MetaMask");
const injectedConnector = createConnector("injected", "Injected");
const coinbaseConnector = createConnector("coinbaseWalletSDK", "Coinbase Wallet");
const walletConnectConnector = createConnector("walletConnect", "WalletConnect");
const hoistedDefaults = vi.hoisted(() => ({
  defaultChain: { id: 2651420, name: "Horizen" } as const,
}));

let currentAccountState: WagmiAccountState;
let currentConnectState: WagmiConnectState;
let currentConnectorsState: Connector[];
let currentDisconnectState: WagmiDisconnectState;
let currentSignMessageState: WagmiSignMessageState;
let currentSwitchChainState: WagmiSwitchChainState;

vi.mock("@/lib/eip6963", () => ({
  ensureEip6963Discovery: vi.fn(),
  getEip6963Providers: vi.fn(() => ({})),
}));

vi.mock("wagmi", () => ({
  useConnection: () => currentAccountState,
  useConnect: () => currentConnectState,
  useConnectors: () => currentConnectorsState,
  useDisconnect: () => currentDisconnectState,
  useSignMessage: () => currentSignMessageState,
  useSwitchChain: () => currentSwitchChainState,
}));

vi.mock("@/lib/wagmi", () => ({
  defaultChain: hoistedDefaults.defaultChain,
}));

describe("ConnectWalletButton", () => {
  beforeEach(() => {
    localStorage.clear();
    (globalThis as any).window = Object.assign(globalThis.window ?? {}, {
      dispatchEvent: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });

    currentAccountState = {
      address: undefined,
      status: "disconnected",
    };
    currentConnectState = {
      mutate: vi.fn(),
      status: "idle",
      error: null,
    };
    currentConnectorsState = [metaMaskConnector, injectedConnector, coinbaseConnector, walletConnectConnector];
    currentDisconnectState = {
      mutate: vi.fn(),
    };
    currentSignMessageState = {
      data: undefined,
      error: null,
      isPending: false,
      mutateAsync: vi.fn(async ({ message }: { message: string }) => `0xsigned-${message}`),
    };
    currentSwitchChainState = {
      error: null,
      isPending: false,
      mutate: vi.fn(),
      mutateAsync: vi.fn().mockResolvedValue(undefined),
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

    expect(currentConnectState.mutate).toHaveBeenCalledWith({ connector: walletConnectConnector });
  });

  it("allows managing a connected session inside the modal", () => {
    currentAccountState = {
      address: "0x1234567890abcdef1234567890abcdef12345678",
      chain: hoistedDefaults.defaultChain,
      status: "connected",
    };

    render(<ConnectWalletButton />);

    expect(screen.getByRole("button", { name: /0x1234...5678/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /0x1234...5678/i }));
    fireEvent.click(screen.getByRole("button", { name: /disconnect/i }));
    expect(currentDisconnectState.mutate).toHaveBeenCalledTimes(1);

    expect(screen.queryByRole("button", { name: /sign message/i })).not.toBeInTheDocument();
  });

  it("renders a fallback when no connectors are available", () => {
    currentConnectorsState = [];

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
      connector: createConnector("injected", "Injected"),
      status: "connected",
    };

    render(<ConnectWalletButton />);
    fireEvent.click(screen.getByRole("button", { name: /0xabcd/i }));

    const switchButton = screen.getByRole("button", {
      name: new RegExp(`switch to ${hoistedDefaults.defaultChain.name}`, "i"),
    });
    expect(switchButton).toBeDisabled();
  });

  it("surfaces a wrong network prompt when switching is unavailable", () => {
    currentAccountState = {
      address: "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
      chain: { id: 1, name: "Other Chain" },
      connector: createConnector("injected", "Injected"),
      status: "connected",
    };

    render(<ConnectWalletButton />);
    fireEvent.click(screen.getByRole("button", { name: /0xabcd/i }));

    expect(screen.getByText(/wrong network/i)).toBeInTheDocument();
    expect(screen.getByText(/switch to .* to continue/i)).toBeInTheDocument();
  });

  it("grays out injected wallets when the browser has no compatible providers", () => {
    currentConnectorsState = [
      createConnector("metaMask", "MetaMask", false),
      createConnector("rabby", "Rabby", false),
      createConnector("okx", "OKX Wallet", false),
      createConnector("injected", "Injected", false),
      createConnector("coinbaseWalletSDK", "Coinbase Wallet", false),
      walletConnectConnector,
    ];

    render(<ConnectWalletButton />);
    fireEvent.click(screen.getByRole("button", { name: /connect wallet/i }));

    expect(screen.getByRole("button", { name: /metamask/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /rabby/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /coinbase wallet/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /okx wallet/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^walletconnect/i })).toBeInTheDocument();
  });
});
