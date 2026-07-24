"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import type { MatrixParams } from "@/lib/api";

const PROJECT_STORAGE_KEY = "quolate-chat-project-id";
const OPEN_STORAGE_KEY = "quolate-chat-open";

function readStoredProjectId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(PROJECT_STORAGE_KEY);
}

interface ChatState {
  projectId: string | null;
  setProjectId: (id: string | null) => void;
  params: MatrixParams;
  setParams: (p: MatrixParams) => void;
  busy: boolean;
  setBusy: (b: boolean) => void;
  onMatrixChanged: (() => void) | null;
  setOnMatrixChanged: (cb: (() => void) | null) => void;
  // Assistant drawer open state, controllable from anywhere (sidebar button,
  // drawer collapse). Persisted so the choice survives navigation/reload.
  chatOpen: boolean;
  setChatOpen: (open: boolean) => void;
}

const ChatContext = createContext<ChatState | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  const [projectId, setProjectIdState] = useState<string | null>(null);
  const [params, setParams] = useState<MatrixParams>({ currency: "USD" });
  const [busy, setBusy] = useState(false);
  const [onMatrixChanged, setOnMatrixChanged] = useState<
    (() => void) | null
  >(null);
  const [chatOpen, setChatOpenState] = useState(false);

  useEffect(() => {
    setProjectIdState(readStoredProjectId());
    // Default: open on wide screens, closed on smaller ones; remember the choice.
    const stored = localStorage.getItem(OPEN_STORAGE_KEY);
    setChatOpenState(stored !== null ? stored === "1" : window.innerWidth >= 1280);
  }, []);

  const setChatOpen = useCallback((open: boolean) => {
    setChatOpenState(open);
    if (typeof window !== "undefined") {
      localStorage.setItem(OPEN_STORAGE_KEY, open ? "1" : "0");
    }
  }, []);

  const setProjectId = useCallback((id: string | null) => {
    setProjectIdState(id);
    if (typeof window !== "undefined") {
      if (id) localStorage.setItem(PROJECT_STORAGE_KEY, id);
      else localStorage.removeItem(PROJECT_STORAGE_KEY);
    }
  }, []);

  return (
    <ChatContext.Provider
      value={{
        projectId,
        setProjectId,
        params,
        setParams,
        busy,
        setBusy,
        onMatrixChanged,
        setOnMatrixChanged,
        chatOpen,
        setChatOpen,
      }}
    >
      {children}
    </ChatContext.Provider>
  );
}

export function useChat(): ChatState {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChat must be used within ChatProvider");
  return ctx;
}
