"use client";

import { PropsWithChildren, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

export function PublicProviders({ children }: PropsWithChildren) {
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

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
