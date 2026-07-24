"use client";

import { useEffect, useRef, useState } from "react";
import type { Document } from "@/lib/api";

const PHASE_LABEL: Record<string, string> = {
  queued: "Queued…",
  extracting: "Extracting text…",
  reading: "Reading with AI…",
  saving: "Saving results…",
};

/**
 * Thin progress bar + phase label + live "time remaining" for a document being
 * parsed. The server sends a fresh {progress, eta_seconds} snapshot on each poll
 * (~2s); between snapshots this ticks locally so the countdown feels live. Local
 * ticking uses only client-side deltas since the last snapshot, so it is immune
 * to clock skew between the browser and the server.
 */
export function ParseProgress({ doc }: { doc: Document }) {
  const active = doc.status === "pending" || doc.status === "processing";
  const serverProgress = doc.progress ?? 0;
  const serverEta = doc.eta_seconds ?? null;
  const phase = doc.phase ?? (doc.status === "pending" ? "queued" : "extracting");

  // Baseline reset on every new server snapshot.
  const base = useRef({ t: Date.now(), progress: serverProgress, eta: serverEta });
  useEffect(() => {
    base.current = { t: Date.now(), progress: serverProgress, eta: serverEta };
  }, [serverProgress, serverEta]);

  const [, forceTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => forceTick((n) => n + 1), 500);
    return () => clearInterval(id);
  }, [active]);

  if (!active) return null;

  const dt = (Date.now() - base.current.t) / 1000;
  const etaRemaining =
    base.current.eta == null ? null : Math.max(0, base.current.eta - dt);

  // Ease the bar toward (near) 100% as the local ETA counts down; never regress.
  let pct = base.current.progress;
  if (base.current.eta && base.current.eta > 0) {
    const headroom = Math.max(0, 0.98 - base.current.progress);
    pct = base.current.progress + headroom * Math.min(1, dt / base.current.eta);
  }
  pct = Math.min(0.98, Math.max(pct, base.current.progress));

  const etaText =
    etaRemaining == null
      ? ""
      : etaRemaining < 1
        ? "finishing up…"
        : `~${Math.ceil(etaRemaining)}s left`;

  return (
    <div className="mt-2">
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={Math.round(pct * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="h-full rounded-full bg-teal transition-[width] duration-500 ease-linear"
          style={{ width: `${Math.round(pct * 100)}%` }}
        />
      </div>
      <div className="mt-1 flex items-center justify-between text-xs text-muted-foreground">
        <span>{PHASE_LABEL[phase] ?? "Processing…"}</span>
        {etaText && <span className="tabular-nums">{etaText}</span>}
      </div>
    </div>
  );
}
