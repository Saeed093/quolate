"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Toaster } from "@/components/ui/toaster";
import { AppShell } from "@/components/AppShell";
import { ChatProvider } from "@/contexts/ChatContext";
import { ActivityProvider } from "@/contexts/ActivityContext";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 5_000, refetchOnWindowFocus: false },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <ActivityProvider>
        <ChatProvider>
          <AppShell>{children}</AppShell>
        </ChatProvider>
      </ActivityProvider>
      <Toaster />
    </QueryClientProvider>
  );
}
