"use client";

import { useMemo } from "react";
import { CheckCircle2, AlertCircle, Loader2, X } from "lucide-react";
import { type PullEvent } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface PullState {
  sourceId: string;
  events: PullEvent[];
  running: boolean;
}

export function PullProgress({
  state,
  onDismiss,
}: {
  state: PullState;
  onDismiss: () => void;
}) {
  const { events, running } = state;

  const summary = useMemo(() => {
    const done = events.find((e) => e.phase === "done");
    const total = events.find((e) => e.total !== undefined)?.total ?? 0;
    const processed = events.filter(
      (e) => e.phase === "notice" && (e.step === "done" || e.step === "error"),
    ).length;
    const latest = [...events]
      .reverse()
      .find((e) => e.phase === "notice");
    return { done, total, processed, latest };
  }, [events]);

  const notices = useMemo(() => {
    const map = new Map<number, PullEvent>();
    for (const e of events) {
      if (e.phase === "notice" && e.index !== undefined) {
        map.set(e.index, e);
      }
    }
    return Array.from(map.values()).sort(
      (a, b) => (a.index ?? 0) - (b.index ?? 0),
    );
  }, [events]);

  const inFlightIdx = summary.latest?.index ?? -1;
  const pct =
    summary.total > 0
      ? Math.round(
          ((summary.processed + (inFlightIdx >= 0 ? 0.5 : 0)) / summary.total) * 100
        )
      : 0;

  const phase = events.length === 0
    ? "Starting…"
    : events[events.length - 1].phase === "listing"
      ? "Listing notices from source…"
      : events[events.length - 1].phase === "fetching"
        ? `Found ${summary.total} notice(s), processing…`
        : summary.done
          ? `Done — ${summary.done.created ?? 0} new, ${summary.done.updated ?? 0} updated`
          : summary.latest
            ? `Processing notice ${(summary.latest.index ?? 0) + 1}/${summary.total}: "${summary.latest.title}" — ${summary.latest.step}…`
            : `Processing ${summary.processed}/${summary.total}…`;

  return (
    <Card className="mb-4 border-primary/30">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          {running ? (
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
          ) : summary.done?.status === "ok" ? (
            <CheckCircle2 className="h-4 w-4 text-ok" />
          ) : (
            <AlertCircle className="h-4 w-4 text-gap" />
          )}
          {phase}
        </CardTitle>
        {!running && (
          <Button size="icon" variant="ghost" onClick={onDismiss} className="h-6 w-6">
            <X className="h-3.5 w-3.5" />
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Progress bar */}
        {summary.total > 0 && (
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>
                {summary.processed} / {summary.total} notices
              </span>
              <span>{pct}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div
                className={cn(
                  "h-full rounded-full transition-all duration-300",
                  summary.done?.status === "ok"
                    ? "bg-ok"
                    : summary.done?.status === "failed"
                      ? "bg-gap"
                      : "bg-primary",
                )}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )}

        {/* Notice list */}
        {notices.length > 0 && (
          <div className="max-h-48 space-y-1 overflow-auto">
            {notices.map((n) => (
              <div
                key={n.index}
                className="flex items-center gap-2 text-xs"
              >
                <NoticeIcon step={n.step} />
                <span className="min-w-0 flex-1 truncate">
                  {n.title}
                </span>
                {n.action && (
                  <Badge
                    variant={n.action === "created" ? "ok" : "secondary"}
                    className="text-[10px] px-1.5 py-0"
                  >
                    {n.action}
                  </Badge>
                )}
                {n.step === "error" && (
                  <Badge variant="gap" className="text-[10px] px-1.5 py-0">
                    error
                  </Badge>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function NoticeIcon({ step }: { step?: string }) {
  if (step === "done")
    return <CheckCircle2 className="h-3 w-3 shrink-0 text-ok" />;
  if (step === "error")
    return <AlertCircle className="h-3 w-3 shrink-0 text-gap" />;
  return <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" />;
}
