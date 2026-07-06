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
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { LlmStatusBadge } from "@/components/LlmStatusBadge";
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
    // "Tenders" shouldn't light up while on /tenders/sources.
    return pathname.startsWith(href) && !pathname.startsWith("/tenders/sources");
  }
  return pathname.startsWith(href);
}

export function AppNav() {
  const router = useRouter();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setMenuOpen(false);
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
    <header className="sticky top-0 z-30 border-b border-border/40 glass shadow-soft">
      <div className="flex h-14 items-center justify-between gap-2 px-4 sm:px-6">
        <div className="flex min-w-0 items-center gap-3 lg:gap-6">
          <Link href="/projects" className="flex shrink-0 items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl gradient-primary text-xs font-bold text-white shadow-soft">
              Q
            </span>
            <span className="text-base font-semibold tracking-tight">
              Quolate
            </span>
          </Link>

          {/* Desktop nav */}
          <nav className="hidden items-center gap-0.5 md:flex">
            {LINKS.map((l) => {
              const active = isActive(pathname, l.href, l.exact);
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  className={cn(
                    "relative rounded-lg px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground",
                    active && "bg-accent text-accent-foreground",
                  )}
                >
                  {l.label}
                  {active && (
                    <span className="absolute inset-x-3 -bottom-[13px] h-0.5 rounded-full bg-primary" />
                  )}
                  {l.href === "/tenders" && badgeCount > 0 && (
                    <Badge
                      variant="gap"
                      className="absolute -right-1.5 -top-1.5 h-4 min-w-4 justify-center px-1 text-[10px]"
                    >
                      {badgeCount}
                    </Badge>
                  )}
                </Link>
              );
            })}
          </nav>
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
          <LlmStatusBadge className="hidden sm:inline-flex" />
          <Button
            variant="ghost"
            size="sm"
            className="hidden gap-1.5 text-muted-foreground hover:text-foreground md:inline-flex"
            onClick={signOut}
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </Button>

          {/* Mobile menu toggle */}
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            onClick={() => setMenuOpen((o) => !o)}
          >
            {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </Button>
        </div>
      </div>

      {/* Mobile nav panel */}
      {menuOpen && (
        <nav className="animate-fade-in-up border-t border-border/40 px-3 py-2 md:hidden">
          {LINKS.map((l) => {
            const active = isActive(pathname, l.href, l.exact);
            const Icon = l.icon;
            return (
              <Link
                key={l.href}
                href={l.href}
                className={cn(
                  "flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground",
                  active && "bg-accent text-accent-foreground",
                )}
              >
                <Icon className="h-4 w-4" />
                {l.label}
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
          <div className="mt-1 flex items-center justify-between border-t border-border/40 px-3 pb-1 pt-2.5">
            <LlmStatusBadge />
            <Button
              variant="ghost"
              size="sm"
              className="gap-1.5 text-muted-foreground hover:text-foreground"
              onClick={signOut}
            >
              <LogOut className="h-3.5 w-3.5" />
              Sign out
            </Button>
          </div>
        </nav>
      )}
    </header>
  );
}
