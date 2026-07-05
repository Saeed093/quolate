"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Send, Loader2, Wrench, Bot, User } from "lucide-react";
import { api, type ChatEvent } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface UiMessage {
  role: "user" | "assistant";
  content: string;
  tools: string[];
  streaming?: boolean;
}

const TOOL_LABELS: Record<string, string> = {
  retrieve_context: "Searched your database",
  search_knowledge: "Searched your database",
  search_tenders: "Searched tenders",
  correlate_tender: "Correlated tender",
  web_search: "Searched the web",
  fetch_url: "Read a web page",
};

function TypingDots() {
  return (
    <span className="inline-flex items-center gap-1 py-0.5">
      <span className="typing-dot" style={{ animationDelay: "0ms" }} />
      <span className="typing-dot" style={{ animationDelay: "160ms" }} />
      <span className="typing-dot" style={{ animationDelay: "320ms" }} />
    </span>
  );
}

/** Whole-database assistant chat (no project scope). */
export function GlobalChatPanel() {
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const history = useQuery({
    queryKey: ["global-chat-history"],
    queryFn: api.globalChatHistory,
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
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
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

    const update = (fn: (msg: UiMessage) => UiMessage) =>
      setMessages((m) => {
        const copy = [...m];
        const last = copy[copy.length - 1];
        if (last && last.role === "assistant") copy[copy.length - 1] = fn(last);
        return copy;
      });

    try {
      await api.streamGlobalChat({ message: text }, (event: ChatEvent) => {
        if (event.type === "tool_call" && event.action) {
          const action = event.action;
          update((msg) => ({ ...msg, tools: [...msg.tools, action] }));
        } else if (event.type === "final") {
          update((msg) => ({
            ...msg,
            content: event.content ?? "",
            streaming: false,
          }));
        }
      });
    } catch (err) {
      update((msg) => ({
        ...msg,
        content:
          err instanceof Error && err.message
            ? err.message
            : "Sorry, the request failed.",
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
            <p className="text-sm font-medium text-foreground">
              Ask me about your data
            </p>
            <p className="mt-1 max-w-[260px] text-xs text-muted-foreground">
              Try &quot;which open tenders match work I&apos;ve done
              before?&quot; or &quot;find my past quotes for transformers&quot;.
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
                    <Bot className="h-2.5 w-2.5" /> Assistant
                  </>
                )}
              </div>

              {m.tools.length > 0 && (
                <div className="mb-1.5 flex flex-wrap gap-1">
                  {m.tools.map((t, j) => (
                    <span
                      key={j}
                      className="animate-fade-in-up inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary"
                    >
                      <Wrench className="h-2.5 w-2.5" /> {TOOL_LABELS[t] ?? t}
                    </span>
                  ))}
                </div>
              )}

              <span className="whitespace-pre-wrap">
                {m.content || (m.streaming ? <TypingDots /> : "")}
              </span>
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
          placeholder="Ask about your tenders, quotes, documents..."
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
            busy ? "animate-pulse" : "gradient-primary hover:shadow-glow",
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
