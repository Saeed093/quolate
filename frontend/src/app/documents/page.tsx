"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useDropzone } from "react-dropzone";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  UploadCloud,
  FileText,
  Trash2,
  Download,
  Eye,
  MessageSquare,
  Loader2,
  Send,
} from "lucide-react";
import { api, getToken, type LibraryDocument } from "@/lib/api";
import { AppNav } from "@/components/AppNav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/use-toast";
import { cn } from "@/lib/utils";

const STATUS_VARIANT: Record<string, "ok" | "verify" | "gap" | "secondary"> = {
  parsed: "ok",
  needs_review: "verify",
  failed: "gap",
  pending: "secondary",
  processing: "secondary",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "queued",
  processing: "processing…",
  parsed: "parsed",
  needs_review: "needs review",
  failed: "failed",
};

export default function DocumentsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [uploadPct, setUploadPct] = useState<number | null>(null);
  const [commentsFor, setCommentsFor] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const docs = useQuery({
    queryKey: ["library-documents"],
    queryFn: api.listLibraryDocuments,
    refetchInterval: (q) => {
      const data = q.state.data as LibraryDocument[] | undefined;
      const busy = data?.some((d) =>
        ["pending", "processing"].includes(d.status),
      );
      return busy ? 2000 : false;
    },
  });

  const upload = useMutation({
    mutationFn: (files: File[]) =>
      api.uploadLibraryDocuments(files, setUploadPct),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["library-documents"] });
      const created = result.created.length;
      const skipped = result.skipped.length;
      const errors = result.errors;
      toast({
        title:
          `Uploaded ${created} file(s)` +
          (skipped ? `, ${skipped} duplicate(s) skipped` : "") +
          (errors.length ? `, ${errors.length} rejected` : ""),
        description: errors.length
          ? errors.map((e) => `${e.filename ?? "?"}: ${e.error}`).join("\n")
          : undefined,
        variant: errors.length ? "destructive" : undefined,
      });
    },
    onError: () => toast({ title: "Upload failed", variant: "destructive" }),
    onSettled: () => setUploadPct(null),
  });

  const del = useMutation({
    mutationFn: (id: string) => api.deleteLibraryDocument(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["library-documents"] });
      toast({ title: "Document deleted" });
    },
    onError: () => toast({ title: "Delete failed", variant: "destructive" }),
  });

  const onDrop = useCallback(
    (accepted: File[]) => {
      if (accepted.length) upload.mutate(accepted);
    },
    [upload],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop });

  // Paste a screenshot anywhere -> upload to the library.
  useEffect(() => {
    function onPaste(e: ClipboardEvent) {
      const files: File[] = [];
      for (const item of Array.from(e.clipboardData?.items ?? [])) {
        if (item.kind === "file" && item.type.startsWith("image/")) {
          const f = item.getAsFile();
          if (f) files.push(f);
        }
      }
      if (files.length) upload.mutate(files);
    }
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [upload]);

  async function openDoc(d: LibraryDocument, inline: boolean) {
    try {
      await api.openLibraryDocument(d.id, d.filename, inline);
    } catch {
      toast({ title: "Could not load file", variant: "destructive" });
    }
  }

  return (
    <div className="min-h-screen">
      <AppNav />
      <main className="mx-auto max-w-4xl px-4 py-6 sm:px-6">
        <h1 className="mb-1 text-2xl font-semibold tracking-tight">Documents</h1>
        <p className="mb-5 text-sm text-muted-foreground">
          Your global document library. Everything uploaded here is indexed so
          the assistant can find and correlate it with tenders and projects.
        </p>

        <div
          {...getRootProps()}
          className={cn(
            "mb-3 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-border bg-card/60 px-4 py-10 text-center transition-all hover:border-primary/40 hover:bg-accent/40",
            isDragActive && "border-primary bg-accent/60 shadow-glow",
          )}
        >
          <input {...getInputProps()} />
          <div className="flex h-11 w-11 items-center justify-center rounded-full bg-accent">
            <UploadCloud className="h-5 w-5 text-accent-foreground" />
          </div>
          <p className="text-sm">
            Drop PDFs, images, Word/PowerPoint docs, Excel, or zips here, or
            click to browse.
          </p>
          <p className="text-xs text-muted-foreground">
            You can also paste a screenshot anywhere on this page.
          </p>
        </div>

        {/* Upload progress */}
        {uploadPct !== null && (
          <div className="mb-6 space-y-1">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>
                {uploadPct < 100 ? "Uploading…" : "Processing upload…"}
              </span>
              <span>{uploadPct}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all duration-200"
                style={{ width: `${uploadPct}%` }}
              />
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {docs.data?.map((d) => (
            <div
              key={d.id}
              className="flex flex-col rounded-xl border border-border/60 bg-card p-3 shadow-soft"
            >
              <div className="flex items-start gap-3">
                <FileText className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <div
                    className="truncate text-sm font-medium"
                    title={d.filename}
                  >
                    {d.filename}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <Badge variant={STATUS_VARIANT[d.status] ?? "secondary"}>
                      {["pending", "processing"].includes(d.status) && (
                        <Loader2 className="mr-1 h-2.5 w-2.5 animate-spin" />
                      )}
                      {STATUS_LABEL[d.status] ?? d.status.replace("_", " ")}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {d.kind}
                    </span>
                  </div>
                  {d.error && (
                    <div
                      className="mt-1 truncate text-xs text-gap"
                      title={d.error}
                    >
                      {d.error}
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-2 flex items-center gap-1 border-t border-border/40 pt-2">
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 gap-1 px-2 text-xs text-muted-foreground"
                  onClick={() => openDoc(d, true)}
                >
                  <Eye className="h-3.5 w-3.5" /> View
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 gap-1 px-2 text-xs text-muted-foreground"
                  onClick={() => openDoc(d, false)}
                >
                  <Download className="h-3.5 w-3.5" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className={cn(
                    "h-7 gap-1 px-2 text-xs text-muted-foreground",
                    commentsFor === d.id && "bg-accent text-accent-foreground",
                  )}
                  onClick={() =>
                    setCommentsFor(commentsFor === d.id ? null : d.id)
                  }
                >
                  <MessageSquare className="h-3.5 w-3.5" />
                  {d.comment_count ? d.comment_count : ""}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="ml-auto h-7 px-2 text-xs text-muted-foreground hover:text-gap"
                  onClick={() => del.mutate(d.id)}
                  aria-label="Delete document"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>

              {commentsFor === d.id && <CommentSection docId={d.id} />}
            </div>
          ))}
        </div>

        {docs.data?.length === 0 && (
          <div className="rounded-2xl border border-dashed border-border py-12 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
              <FileText className="h-5 w-5 text-muted-foreground" />
            </div>
            <p className="text-sm font-medium">No documents yet</p>
            <p className="mx-auto mt-1 max-w-xs text-xs text-muted-foreground">
              Upload past quotations, BOMs, contracts, photos — anything you
              want the assistant to know about.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}

function CommentSection({ docId }: { docId: string }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");

  const comments = useQuery({
    queryKey: ["document-comments", docId],
    queryFn: () => api.listDocumentComments(docId),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["document-comments", docId] });
    qc.invalidateQueries({ queryKey: ["library-documents"] });
  };

  const add = useMutation({
    mutationFn: (content: string) => api.addDocumentComment(docId, content),
    onSuccess: () => {
      setText("");
      invalidate();
    },
    onError: () =>
      toast({ title: "Could not add comment", variant: "destructive" }),
  });

  const del = useMutation({
    mutationFn: (commentId: string) =>
      api.deleteDocumentComment(docId, commentId),
    onSuccess: invalidate,
  });

  return (
    <div className="mt-2 space-y-2 border-t border-border/40 pt-2">
      {comments.data?.map((c) => (
        <div key={c.id} className="group flex items-start gap-2">
          <div className="min-w-0 flex-1 rounded-lg bg-muted/60 px-2.5 py-1.5">
            <p className="whitespace-pre-wrap text-xs">{c.content}</p>
            {c.created_at && (
              <p className="mt-0.5 text-[10px] text-muted-foreground">
                {new Date(c.created_at).toLocaleString()}
              </p>
            )}
          </div>
          <button
            className="mt-1 shrink-0 rounded p-0.5 text-muted-foreground opacity-0 transition-opacity hover:text-gap group-hover:opacity-100"
            onClick={() => del.mutate(c.id)}
            aria-label="Delete comment"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      ))}
      {comments.data?.length === 0 && (
        <p className="text-[11px] text-muted-foreground">
          No comments yet. Notes you add here are visible to the assistant.
        </p>
      )}
      <form
        className="flex items-center gap-1.5"
        onSubmit={(e) => {
          e.preventDefault();
          const content = text.trim();
          if (content && !add.isPending) add.mutate(content);
        }}
      >
        <Input
          placeholder="Add a note about this document..."
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="h-8 text-xs"
        />
        <Button
          type="submit"
          size="icon"
          variant="ghost"
          className="h-8 w-8 shrink-0"
          disabled={add.isPending || !text.trim()}
          aria-label="Add comment"
        >
          {add.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Send className="h-3.5 w-3.5" />
          )}
        </Button>
      </form>
    </div>
  );
}
