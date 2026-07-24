"use client";

import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export interface WorkflowStep {
  key: string;
  label: string;
}

/**
 * Horizontal numbered progress bar for the guided project workflow. Completed
 * steps show a check and are clickable so the user can jump back; upcoming
 * steps are reachable too (the flow guides, it doesn't lock).
 */
export function WorkflowStepper({
  steps,
  current,
  onStep,
}: {
  steps: WorkflowStep[];
  current: number;
  onStep: (index: number) => void;
}) {
  return (
    <nav aria-label="Progress" className="overflow-x-auto">
      <ol className="flex min-w-max items-center gap-1">
        {steps.map((s, i) => {
          const done = i < current;
          const active = i === current;
          return (
            <li key={s.key} className="flex flex-1 items-center gap-1">
              <button
                type="button"
                onClick={() => onStep(i)}
                aria-current={active ? "step" : undefined}
                className={cn(
                  "flex shrink-0 items-center gap-2 rounded-full px-2.5 py-1.5 text-sm transition-colors",
                  active
                    ? "bg-teal/10 font-semibold text-teal"
                    : "text-muted-foreground hover:bg-muted",
                )}
              >
                <span
                  className={cn(
                    "flex h-6 w-6 items-center justify-center rounded-full border text-xs font-semibold tabular-nums",
                    active
                      ? "border-teal bg-teal text-white"
                      : done
                        ? "border-teal bg-teal/15 text-teal"
                        : "border-border text-muted-foreground",
                  )}
                >
                  {done ? <Check className="h-3.5 w-3.5" /> : i + 1}
                </span>
                <span className="whitespace-nowrap">{s.label}</span>
              </button>
              {i < steps.length - 1 && (
                <span
                  className={cn(
                    "h-px flex-1 rounded",
                    done ? "bg-teal/40" : "bg-border",
                  )}
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
