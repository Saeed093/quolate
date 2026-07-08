// Receives client-side error reports and appends them as plain text to
// frontend/logs/errors.log (the browser cannot write files itself).
import { appendFile, mkdir } from "fs/promises";
import path from "path";

export const runtime = "nodejs";

interface ErrorReport {
  when?: string;
  action?: string;
  message?: string;
  possibleIssue?: string;
  url?: string;
  stack?: string;
}

const clip = (s: unknown, n: number) =>
  typeof s === "string" ? s.slice(0, n) : "";

export async function POST(req: Request) {
  try {
    const body = (await req.json()) as ErrorReport;
    const when = clip(body.when, 40) || new Date().toISOString();
    const lines = [
      `[${when}]`,
      `user action:    ${clip(body.action, 300) || "unknown"}`,
      `error:          ${clip(body.message, 2000) || "unknown"}`,
      `possible issue: ${clip(body.possibleIssue, 500) || "unknown"}`,
      `page:           ${clip(body.url, 500)}`,
    ];
    if (body.stack) lines.push(`stack:\n${clip(body.stack, 4000)}`);
    const dir = path.join(process.cwd(), "logs");
    await mkdir(dir, { recursive: true });
    await appendFile(
      path.join(dir, "errors.log"),
      lines.join("\n") + "\n\n",
      "utf8",
    );
  } catch {
    // Logging must never break the app.
  }
  return new Response(null, { status: 204 });
}
