"use client";

import { useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Cpu, Loader2, Zap } from "lucide-react";
import { api, ApiError, type LlmStatus } from "@/lib/api";
import { useChat } from "@/contexts/ChatContext";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const REASON_MESSAGES: Record<string, string> = {
  ollama_offline: "Ollama is not running. Start it, then try again.",
  no_gpu: "No compatible GPU was detected on this system.",
  model_not_loaded: "The model is not loaded on the GPU yet.",
  model_on_cpu: "The model is currently running on CPU. Chat only runs on GPU.",
  insufficient_vram: "The model does not fit fully in GPU memory.",
};

/**
 * Blocks the chat UI unless the LLM is fully running on a GPU.
 * Shows a "Start GPU" button instead; if the backend reports no GPU
 * installed (409), pops the "No GPU available" dialog.
 */
export function GpuGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { busy } = useChat();
  const [starting, setStarting] = useState(false);
  const [noGpuOpen, setNoGpuOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const status = useQuery({
    queryKey: ["llm-status"],
    queryFn: api.llmStatus,
    refetchInterval: 10_000,
    retry: false,
  });

  async function startGpu() {
    setStarting(true);
    setError(null);
    try {
      const fresh = await api.startGpu();
      queryClient.setQueryData<LlmStatus>(["llm-status"], fresh);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setNoGpuOpen(true);
      } else {
        setError(
          err instanceof Error && err.message
            ? err.message
            : "Could not start the GPU.",
        );
      }
      queryClient.invalidateQueries({ queryKey: ["llm-status"] });
    } finally {
      setStarting(false);
    }
  }

  // Never yank the panel away while a reply is streaming — re-gate only
  // once the exchange has finished.
  if (busy || status.data?.chat_available) return <>{children}</>;

  if (status.isPending) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const detail = status.data
    ? (REASON_MESSAGES[status.data.reason ?? ""] ?? "Chat is unavailable.")
    : "Cannot reach the server.";

  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
        <Cpu className="h-6 w-6 text-muted-foreground" />
      </div>
      <div>
        <p className="text-sm font-semibold text-foreground">
          Chat runs on GPU only
        </p>
        <p className="mt-1 max-w-[280px] text-xs text-muted-foreground">
          {detail}
        </p>
      </div>
      <Button
        onClick={startGpu}
        disabled={starting}
        className="bg-ink-deep text-paper"
      >
        {starting ? (
          <>
            <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            Starting GPU…
          </>
        ) : (
          <>
            <Zap className="mr-1.5 h-4 w-4" />
            Start GPU
          </>
        )}
      </Button>
      {error && (
        <p className="max-w-[280px] text-xs text-red-600">{error}</p>
      )}

      <Dialog open={noGpuOpen} onOpenChange={setNoGpuOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>No GPU available</DialogTitle>
            <DialogDescription>
              No GPU is installed on this system. Chat requires a GPU and
              cannot be enabled.
            </DialogDescription>
          </DialogHeader>
          <Button onClick={() => setNoGpuOpen(false)}>OK</Button>
        </DialogContent>
      </Dialog>
    </div>
  );
}
