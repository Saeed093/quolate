"use client";

import { useQuery } from "@tanstack/react-query";
import { MessageSquare, PanelRightClose } from "lucide-react";
import { useChat } from "@/contexts/ChatContext";
import { ChatPanel } from "@/components/workbench/ChatPanel";
import { GlobalChatPanel } from "@/components/GlobalChatPanel";
import { GpuGate } from "@/components/GpuGate";
import { LlmStatusBadge } from "@/components/LlmStatusBadge";
import { api, getToken } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function GlobalChatDrawer() {
  const { projectId, setProjectId, params, onMatrixChanged, chatOpen, setChatOpen } =
    useChat();

  function toggle(next: boolean) {
    setChatOpen(next);
  }

  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: api.listProjects,
    enabled: !!getToken(),
  });

  // Opened from the sidebar's Assistant button; nothing floats when closed.
  if (!chatOpen) return null;

  return (
    <>
      {/* Backdrop on smaller screens where the drawer overlays content */}
      <div
        className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[2px] animate-fade-in xl:hidden"
        onClick={() => toggle(false)}
        aria-hidden
      />
      <aside
        className={cn(
          "fixed inset-y-0 right-0 z-40 flex w-full max-w-[420px] flex-col border-l border-border/50 bg-white shadow-drawer animate-slide-in-right",
          "xl:sticky xl:top-0 xl:z-auto xl:h-screen xl:w-[380px] xl:max-w-none xl:shrink-0 xl:animate-none 2xl:w-[420px]",
        )}
      >
        <div className="flex shrink-0 flex-col gap-2 border-b border-border/60 px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink-deep text-paper">
                <MessageSquare className="h-4 w-4" />
              </div>
              <div>
                <h2 className="text-sm font-semibold">Assistant</h2>
                <p className="text-[11px] text-muted-foreground">
                  {projectId
                    ? "Project copilot — drives the matrix"
                    : "Searches everything in your database"}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <LlmStatusBadge />
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-muted-foreground"
                onClick={() => toggle(false)}
                aria-label="Collapse assistant"
              >
                <PanelRightClose className="h-4 w-4" />
              </Button>
            </div>
          </div>

          <select
            className="select-base h-9 bg-muted/40 text-sm"
            value={projectId ?? ""}
            onChange={(e) => setProjectId(e.target.value || null)}
          >
            <option value="">Everything (all data)</option>
            {projects.data?.map((p) => (
              <option key={p.id} value={p.id}>
                Project: {p.name}
              </option>
            ))}
          </select>
        </div>

        <div className="min-h-0 flex-1">
          <GpuGate>
            {projectId ? (
              <ChatPanel
                key={projectId}
                projectId={projectId}
                params={params}
                onMatrixChanged={onMatrixChanged ?? (() => {})}
              />
            ) : (
              <GlobalChatPanel key="global" />
            )}
          </GpuGate>
        </div>
      </aside>
    </>
  );
}
