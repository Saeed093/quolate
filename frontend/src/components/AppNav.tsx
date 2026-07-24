"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LogOut,
  Menu,
  X,
  FolderKanban,
  Landmark,
  Rss,
  FileText,
  Calculator,
  Sparkles,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { LlmStatusBadge } from "@/components/LlmStatusBadge";
import { QuolateLockup } from "@/components/QuolateLockup";
import { useChat } from "@/contexts/ChatContext";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/tenders", label: "Tenders", icon: Landmark, exact: true },
  { href: "/tenders/sources", label: "Sources", icon: Rss },
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/duty-calculator", label: "Duty Calculator", icon: Calculator },
];

function isActive(pathname: string | null, href: string, exact?: boolean) {
  if (!pathname) return false;
  if (exact) {
    return pathname.startsWith(href) && !pathname.startsWith("/tenders/sources");
  }
  return pathname.startsWith(href);
}

function SidebarNav({
  pathname,
  badgeCount,
  onNavigate,
  className,
}: {
  pathname: string | null;
  badgeCount: number;
  onNavigate?: () => void;
  className?: string;
}) {
  return (
    <nav className={cn("flex flex-1 flex-col gap-1 px-3 py-2", className)}>
      {LINKS.map((l) => {
        const active = isActive(pathname, l.href, l.exact);
        const Icon = l.icon;
        return (
          <Link
            key={l.href}
            href={l.href}
            onClick={onNavigate}
            className={cn(
              "relative flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium text-slate-soft transition-colors hover:bg-white/8 hover:text-paper",
              active && "bg-white/8 text-paper",
            )}
          >
            {active && (
              <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-teal" />
            )}
            <Icon className="h-4 w-4 shrink-0" />
            <span className="truncate">{l.label}</span>
            {l.href === "/tenders" && badgeCount > 0 && (
              <Badge
                variant="gap"
                className="ml-auto h-4 min-w-4 justify-center px-1 text-[10px]"
              >
                {badgeCount}
              </Badge>
            )}
          </Link>
        );
      })}
    </nav>
  );
}

export function AppShell({
  children,
  fullHeight,
}: {
  children: React.ReactNode;
  fullHeight?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { chatOpen, setChatOpen, busy } = useChat();

  useEffect(() => {
    setSidebarOpen(false);
  }, [pathname]);

  const badge = useQuery({
    queryKey: ["tender-badge"],
    queryFn: api.notificationBadge,
    refetchInterval: 60_000,
  });
  const badgeCount = badge.data?.count ?? 0;

  function signOut() {
    api.logout();
    router.push("/login");
  }

  return (
    <div
      className={cn("flex", fullHeight ? "h-screen overflow-hidden" : "min-h-screen")}
    >
      {sidebarOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          className="fixed inset-0 z-40 bg-black/40 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-white/10 bg-ink-deep text-paper shadow-soft transition-transform duration-200 ease-out md:sticky md:top-0 md:z-30 md:h-screen md:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-white/10 px-4">
          <Link
            href="/projects"
            className="min-w-0"
            onClick={() => setSidebarOpen(false)}
          >
            <QuolateLockup variant="dark" />
          </Link>
          <Button
            variant="ghost"
            size="icon"
            className="text-paper hover:bg-white/10 hover:text-paper md:hidden"
            aria-label="Close navigation"
            onClick={() => setSidebarOpen(false)}
          >
            <X className="h-5 w-5" />
          </Button>
        </div>

        <SidebarNav
          pathname={pathname}
          badgeCount={badgeCount}
          onNavigate={() => setSidebarOpen(false)}
        />

        <div className="mt-auto flex flex-col gap-2 border-t border-white/10 px-3 py-3">
          <button
            type="button"
            onClick={() => setChatOpen(!chatOpen)}
            aria-label={chatOpen ? "Hide assistant" : "Open assistant"}
            className={cn(
              "flex w-full items-center justify-center gap-2 rounded-lg bg-teal px-3 py-2.5 text-sm font-semibold text-ink-deep shadow-lift transition-all hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal/50",
              busy && "animate-pulse",
            )}
          >
            <Sparkles className="h-4 w-4" />
            Assistant
          </button>
          <LlmStatusBadge className="dark-surface" />
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start gap-1.5 text-slate-soft hover:bg-white/10 hover:text-paper"
            onClick={signOut}
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-paper px-4 shadow-soft md:hidden">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Open navigation"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu className="h-5 w-5" />
          </Button>
          <Link href="/projects">
            <QuolateLockup variant="sm" />
          </Link>
        </header>

        <div className={cn("flex min-h-0 flex-1 flex-col", fullHeight && "overflow-hidden")}>
          {children}
        </div>
      </div>
    </div>
  );
}

/** @deprecated Use AppShell instead */
export const AppNav = AppShell;
