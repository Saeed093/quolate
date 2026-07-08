"use client";

import { useEffect } from "react";
import { logClientError } from "@/lib/error-log";

/** Catches uncaught browser errors / promise rejections and logs them to
 * frontend/logs/errors.log. Renders nothing. */
export function ClientErrorLogger() {
  useEffect(() => {
    const onError = (event: ErrorEvent) => {
      logClientError(
        `uncaught error at ${event.filename ?? "?"}:${event.lineno ?? "?"}`,
        event.error ?? event.message,
      );
    };
    const onRejection = (event: PromiseRejectionEvent) => {
      logClientError("unhandled promise rejection", event.reason);
    };
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);
  return null;
}
