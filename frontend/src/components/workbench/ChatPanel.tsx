"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Send, Loader2, Wrench, Bot, User } from "lucide-react";
import { api, type ChatEvent, type MatrixParams } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useChat } from "@/contexts/ChatContext";
import { ChatMessageContent } from "@/components/ChatMessageContent";
import { cn } from "@/lib/utils";

interface UiMessage {
  role: "user" | "assistant";
  content: string;
  tools: string[];
  streaming?: boolean;
}

function TypingDots() {
  return (
    <span className="inline-flex items-center gap-1 py-0.5">
      <span className="typing-dot" style={{ animationDelay: "0ms" }} />
      <span className="typing-dot" style={{ animationDelay: "160ms" }} />
      <span className="typing-dot" style={{ animationDelay: "320ms" }} />
    </span>
  );
}

export function ChatPanel({
  projectId,
  params,
  onMatrixChanged,
}: {
  projectId: string;
  params: MatrixParams;
  onMatrixChanged: () => void;
}) {
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusyLocal] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const { setBusy: setGlobalBusy } = useChat();

  function setBusy(b: boolean) {
    setBusyLocal(b);
    setGlobalBusy(b);
  }

  const history = useQuery({
    queryKey: ["chat-history", projectId],
    queryFn: () => api.chatHistory(projectId),
  });

  useEffect(() => {
    if (history.data && messages.length === 0) {
      setMessages(
        history.data
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({
            role: m.role as "user" | "assistant",
            content: m.content,
            tools: [],
          })),
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history.data]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setMessages((m) => [
      ...m,
      { role: "user", content: text, tools: [] },
      { role: "assistant", content: "", tools: [], streaming: true },
    ]);

    const overrides: Record<string, number> = {};
    if (params.duty_pct !== undefined) overrides.duty_pct = params.duty_pct;
    if (params.freight_per_unit !== undefined)
      overrides.freight_per_unit = params.freight_per_unit;
    if (params.lc_pct !== undefined) overrides.lc_pct = params.lc_pct;

    const update = (fn: (msg: UiMessage) => UiMessage) =>
      setMessages((m) => {
        const copy = [...m];
        const last = copy[copy.length - 1];
        if (last && last.role === "assistant") copy[copy.length - 1] = fn(last);
        return copy;
      });

    try {
      await api.streamChat(
        projectId,
        { message: text, currency: params.currency, overrides },
        (event: ChatEvent) => {
          if (event.type === "tool_call" && event.action) {
            const action = event.action;
            update((msg) => ({ ...msg, tools: [...msg.tools, action] }));
          } else if (event.type === "final") {
            update((msg) => ({
              ...msg,
              content: event.content ?? "",
              streaming: false,
            }));
            if (event.matrix_changed) onMatrixChanged();
          }
        },
      );
    } catch {
      update((msg) => ({
        ...msg,
        content: "Sorry, the chat request failed.",
        streaming: false,
      }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* Messages */}
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-auto p-4">
        {messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-accent">
              <Bot className="h-5 w-5 text-accent-foreground" />
            </div>
            <p className="text-sm font-medium text-foreground">How can I help?</p>
            <p className="mt-1 max-w-[260px] text-xs text-muted-foreground">
              Try &quot;recompute landed cost at 15% duty&quot; or &quot;search
              the web for thermal camera suppliers&quot;.
            </p>
          </div>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={cn(
              "animate-slide-in-up",
              m.role === "user" ? "flex justify-end" : "flex justify-start",
            )}
          >
            <div
              className={cn(
                "group relative max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
                m.role === "user"
                  ? "gradient-primary text-white rounded-br-md"
                  : "bg-muted/80 text-foreground rounded-bl-md",
              )}
            >
              {/* Avatar chip */}
              <div
                className={cn(
                  "mb-1 flex items-center gap-1 text-[10px] font-medium uppercase tracking-wider opacity-60",
                  m.role === "user" ? "justify-end" : "justify-start",
                )}
              >
                {m.role === "user" ? (
                  <>
                    You <User className="h-2.5 w-2.5" />
                  </>
                ) : (
                  <>
                    <Bot className="h-2.5 w-2.5" /> Copilot
                  </>
                )}
              </div>

              {/* Tool call badges */}
              {m.tools.length > 0 && (
                <div className="mb-1.5 flex flex-wrap gap-1">
                  {m.tools.map((t, j) => (
                    <span
                      key={j}
                      className="animate-fade-in-up inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary"
                    >
                      <Wrench className="h-2.5 w-2.5" />{" "}
                      {t === "retrieve_context" ? "Searched your database" : t}
                    </span>
                  ))}
                </div>
              )}

              {/* Content or typing indicator */}
              {m.content ? (
                <ChatMessageContent content={m.content} />
              ) : m.streaming ? (
                <TypingDots />
              ) : null}
            </div>
          </div>
        ))}
      </div>

      {/* Input */}
      <form
        className="flex items-center gap-2 border-t border-border/60 bg-white p-3"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <Input
          placeholder="Message the copilot..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={busy}
          className="rounded-xl border-border/60 bg-muted/40 focus:bg-white"
        />
        <Button
          type="submit"
          size="icon"
          disabled={busy}
          aria-label="Send"
          className={cn(
            "h-9 w-9 shrink-0 rounded-xl transition-all",
            busy
              ? "animate-pulse"
              : "gradient-primary hover:shadow-glow",
          )}
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin text-white" />
          ) : (
            <Send className="h-4 w-4 text-white" />
          )}
        </Button>
      </form>
    </div>
  );
}
