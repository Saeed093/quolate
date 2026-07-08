"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export function LlmStatusBadge({ className }: { className?: string }) {
  const { data } = useQuery({
    queryKey: ["llm-status"],
    queryFn: api.llmStatus,
    refetchInterval: 10_000,
    retry: false,
  });

  const online = data?.online ?? false;
  const gpu = data?.gpu ?? false;
  const label = !online ? "Offline" : gpu ? "GPU" : "CPU";
  const onDark = className?.includes("dark-surface");

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium leading-none transition-colors",
        online
          ? gpu
            ? "border-ok/30 bg-ok/10 text-ok"
            : onDark
              ? "border-white/20 bg-white/8 text-slate-soft"
              : "border-slate/20 bg-slate/10 text-slate"
          : "border-gap/30 bg-gap/10 text-gap",
        className,
      )}
      title={
        online
          ? `${data?.model ?? "LLM"} running on ${gpu ? "GPU" : "CPU"}${data?.vram_used ? ` (${data.vram_used})` : ""}${data?.gpu_name ? ` — ${data.gpu_name}` : ""}`
          : "Ollama is not reachable"
      }
    >
      <span className="relative flex h-2 w-2">
        {online ? (
          <span className="h-2 w-2 rounded-full bg-current" />
        ) : (
          <>
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-current" />
          </>
        )}
      </span>
      {label}
    </div>
  );
}
