// Client-side error logging: what the user did, what failed, and a heuristic
// "possible issue". Reports go to the Next server route /api/log-error which
// appends them to frontend/logs/errors.log.

function guessIssue(action: string, message: string, status?: number): string {
  const text = `${action} ${message}`.toLowerCase();
  if (message === "Failed to fetch" || text.includes("networkerror")) {
    return "Backend unreachable — is the FastAPI server on :8000 running?";
  }
  if (status === 503 || text.includes("gpu") || text.includes("ollama")) {
    return "LLM/GPU not ready — click 'Start GPU' or check that Ollama is running.";
  }
  if (status === 401 || status === 403) {
    return "Not logged in or session expired — log in again.";
  }
  if (status === 422) {
    return "Invalid form input — check the values that were submitted.";
  }
  if (status === 409) {
    return "Conflict (e.g. no GPU installed, or duplicate data).";
  }
  if (text.includes("timed out") || text.includes("timeout")) {
    return "The model or server took too long — retry, or check GPU status.";
  }
  if (status !== undefined && status >= 500) {
    return "Server error — check backend/logs/errors.log for the traceback.";
  }
  return "Unclassified — see the error message.";
}

/**
 * Log an error to frontend/logs/errors.log. `action` should describe what the
 * user was doing (e.g. "POST /chat", "upload invoice"). Fire-and-forget.
 */
export function logClientError(
  action: string,
  error: unknown,
  status?: number,
): void {
  if (typeof window === "undefined") return;
  const message =
    error instanceof Error ? error.message : String(error ?? "unknown");
  const stack = error instanceof Error ? error.stack : undefined;
  try {
    void fetch("/api/log-error", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      keepalive: true,
      body: JSON.stringify({
        when: new Date().toISOString(),
        action,
        message: status !== undefined ? `HTTP ${status}: ${message}` : message,
        possibleIssue: guessIssue(action, message, status),
        url: window.location.pathname,
        stack,
      }),
    }).catch(() => {});
  } catch {
    // Logging must never break the app.
  }
}
