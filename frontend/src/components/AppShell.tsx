"use client";

import { usePathname } from "next/navigation";
import { GlobalChatDrawer } from "@/components/GlobalChatDrawer";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  const isAuthPage =
    pathname === "/login" || pathname === "/register" || pathname === "/";

  if (isAuthPage) return children;

  return (
    <div className="flex min-h-screen">
      <div className="min-w-0 flex-1">{children}</div>
      <GlobalChatDrawer />
    </div>
  );
}
