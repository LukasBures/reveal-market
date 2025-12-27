"use client";

import { PropsWithChildren, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WagmiProvider } from "wagmi";
import { wagmiConfig } from "@/lib/wagmi";

export function AppProviders({ children }: PropsWithChildren) {
  const queryClientConfig =
    process.env.NODE_ENV === "test"
      ? {
          defaultOptions: {
            queries: { gcTime: 0 },
            mutations: { gcTime: 0 },
          },
        }
      : undefined;
  const [queryClient] = useState(() => new QueryClient(queryClientConfig));

  return (
    <WagmiProvider config={wagmiConfig}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </WagmiProvider>
  );
}
