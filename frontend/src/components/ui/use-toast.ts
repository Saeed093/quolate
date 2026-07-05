"use client";

import * as React from "react";

type ToastItem = {
  id: string;
  title?: React.ReactNode;
  description?: React.ReactNode;
  variant?: "default" | "destructive";
  open: boolean;
};

type Listener = (toasts: ToastItem[]) => void;

let toasts: ToastItem[] = [];
const listeners: Listener[] = [];
const TIMEOUT = 4000;

function emit() {
  for (const l of listeners) l([...toasts]);
}

export function toast(opts: {
  title?: React.ReactNode;
  description?: React.ReactNode;
  variant?: "default" | "destructive";
}) {
  const id = Math.random().toString(36).slice(2);
  toasts = [{ ...opts, id, open: true }, ...toasts].slice(0, 4);
  emit();
  setTimeout(() => dismiss(id), TIMEOUT);
  return id;
}

export function dismiss(id: string) {
  toasts = toasts.map((t) => (t.id === id ? { ...t, open: false } : t));
  emit();
  setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== id);
    emit();
  }, 300);
}

export function useToast() {
  const [state, setState] = React.useState<ToastItem[]>(toasts);
  React.useEffect(() => {
    listeners.push(setState);
    return () => {
      const i = listeners.indexOf(setState);
      if (i > -1) listeners.splice(i, 1);
    };
  }, []);
  return { toasts: state, toast, dismiss };
}
