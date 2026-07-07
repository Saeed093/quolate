"use client";

import { type HsCandidate } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

/** Ranked HS-code suggestions as clickable buttons.
 *
 * `compact` renders inline chips (code + confidence only) for table rows;
 * the default renders the full card-style buttons with description and
 * reasoning used by the single-item classifier.
 */
export function CandidateButtons({
  candidates,
  onPick,
  compact = false,
  selectedHsCode,
}: {
  candidates: HsCandidate[];
  onPick: (candidate: HsCandidate) => void;
  compact?: boolean;
  selectedHsCode?: string;
}) {
  if (compact) {
    return (
      <div className="flex flex-wrap gap-1.5">
        {candidates.map((c, i) => {
          const selected = selectedHsCode === c.hs_code;
          return (
            <button
              key={`${c.hs_code}-${i}`}
              type="button"
              onClick={() => onPick(c)}
              title={[c.description, c.reasoning].filter(Boolean).join(" — ")}
              className={
                "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors " +
                (selected
                  ? "border-primary bg-primary/10 font-semibold"
                  : "border-border/70 hover:border-primary/50 hover:bg-accent")
              }
            >
              <span className="font-mono">{c.hs_code}</span>
              <Badge
                variant={c.confidence < 0.5 ? "verify" : "ok"}
                className="text-[10px]"
              >
                {Math.round(c.confidence * 100)}%
              </Badge>
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {candidates.map((c, i) => {
        const lowConfidence = c.confidence < 0.5;
        return (
          <button
            key={`${c.hs_code}-${i}`}
            type="button"
            onClick={() => onPick(c)}
            className="flex items-start justify-between gap-3 rounded-xl border border-border/70 px-3.5 py-2.5 text-left transition-colors hover:border-primary/50 hover:bg-accent"
          >
            <div className="flex flex-col gap-0.5">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-semibold">{c.hs_code}</span>
                <Badge variant={lowConfidence ? "verify" : "ok"} className="text-[10px]">
                  {Math.round(c.confidence * 100)}% confidence
                </Badge>
              </div>
              {c.description && (
                <p className="text-xs text-muted-foreground">{c.description}</p>
              )}
              {c.reasoning && (
                <p className="text-[11px] text-muted-foreground">{c.reasoning}</p>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}
