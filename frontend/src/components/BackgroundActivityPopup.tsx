"use client";

import { usePathname } from "next/navigation";
import { FileText, Loader2, RefreshCw } from "lucide-react";
import { useActivity } from "@/contexts/ActivityContext";
import { cn } from "@/lib/utils";

export function BackgroundActivityPopup() {
  const pathname = usePathname();
  const { uploads, activity } = useActivity();

  const isAuthPage =
    pathname === "/login" || pathname === "/register" || pathname === "/";

  if (isAuthPage) return null;

  const processing = activity?.documents_processing ?? 0;
  const pulls = activity?.tender_pulls ?? [];
  const hasActivity = uploads.length > 0 || processing > 0 || pulls.length > 0;

  if (!hasActivity) return null;

  return (
    <div
      className="fixed bottom-4 left-4 z-[90] w-72 overflow-hidden rounded-xl border border-border/60 bg-card/95 shadow-soft backdrop-blur-sm"
      role="status"
      aria-live="polite"
    >
      <div className="border-b border-border/50 bg-muted/40 px-3 py-2">
        <p className="text-xs font-medium text-muted-foreground">
          Background activity
        </p>
      </div>
      <ul className="max-h-48 space-y-0 divide-y divide-border/40 overflow-auto">
        {uploads.map((u) => (
          <li key={u.id} className="px-3 py-2.5">
            <div className="flex items-start gap-2">
              <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-primary" />
              <div className="min-w-0 flex-1 space-y-1.5">
                <p className="text-sm leading-tight">{u.label}</p>
                {u.percent !== null && (
                  <>
                    <div className="flex justify-between text-[11px] text-muted-foreground">
                      <span>
                        {u.percent < 100 ? "Uploading…" : "Finishing…"}
                      </span>
                      <span>{u.percent}%</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-primary transition-all duration-200"
                        style={{ width: `${u.percent}%` }}
                      />
                    </div>
                  </>
                )}
              </div>
            </div>
          </li>
        ))}

        {processing > 0 && (
          <li className="px-3 py-2.5">
            <div className="flex items-center gap-2">
              <FileText className="h-3.5 w-3.5 shrink-0 text-primary" />
              <p className="text-sm">
                Processing {processing} document
                {processing === 1 ? "" : "s"}…
              </p>
              <Loader2
                className={cn(
                  "ml-auto h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground",
                  uploads.length > 0 && "hidden",
                )}
              />
            </div>
          </li>
        )}

        {pulls.map((p) => (
          <li key={p.source_id} className="px-3 py-2.5">
            <div className="flex items-center gap-2">
              <RefreshCw className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" />
              <p className="min-w-0 truncate text-sm">
                Pulling tenders from {p.source_name}
                {p.status === "queued" ? " (queued)" : ""}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
