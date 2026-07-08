"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
  FolderOpen,
} from "lucide-react";
import { api, getToken, type LibraryDocument } from "@/lib/api";
import { useActivity } from "@/contexts/ActivityContext";
import { AppShell } from "@/components/AppNav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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

type SortOption = "newest" | "oldest" | "name";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DocumentsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const { startUpload, setUploadProgress, endUpload, uploads } = useActivity();
  const libraryUpload = uploads.find((u) => u.id === "library");
  const [commentsFor, setCommentsFor] = useState<string | null>(null);
  const [sort, setSort] = useState<SortOption>("newest");
  const [projectFilter, setProjectFilter] = useState<string>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const quota = useQuery({
    queryKey: ["library-quota"],
    queryFn: api.libraryQuota,
  });

  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: api.listProjects,
  });

  const listParams = useMemo(
    () => ({
      sort,
      ...(projectFilter === "all"
        ? {}
        : { project_id: projectFilter }),
    }),
    [sort, projectFilter],
  );

  const docs = useQuery({
    queryKey: ["library-documents", listParams],
    queryFn: () => api.listLibraryDocuments(listParams),
    refetchInterval: (q) => {
      const data = q.state.data as LibraryDocument[] | undefined;
      const busy = data?.some((d) =>
        ["pending", "processing"].includes(d.status),
      );
      return busy ? 2000 : false;
    },
  });

  const quotaFull =
    quota.data != null && quota.data.used_bytes >= quota.data.limit_bytes;

  const upload = useMutation({
    mutationFn: (files: File[]) => {
      startUpload("library", `Uploading ${files.length} file(s)…`);
      return api.uploadLibraryDocuments(files, (pct) =>
        setUploadProgress("library", pct),
      );
    },
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["library-documents"] });
      qc.invalidateQueries({ queryKey: ["library-quota"] });
      qc.invalidateQueries({ queryKey: ["activity"] });
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
    onSettled: () => endUpload("library"),
  });

  const del = useMutation({
    mutationFn: (id: string) => api.deleteLibraryDocument(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["library-documents"] });
      qc.invalidateQueries({ queryKey: ["library-quota"] });
      toast({ title: "Document deleted" });
    },
    onError: () => toast({ title: "Delete failed", variant: "destructive" }),
  });

  const bulkDel = useMutation({
    mutationFn: (ids: string[]) => api.bulkDeleteLibraryDocuments(ids),
    onSuccess: (result) => {
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ["library-documents"] });
      qc.invalidateQueries({ queryKey: ["library-quota"] });
      toast({
        title: `Deleted ${result.count} document(s)`,
        description:
          result.not_found.length > 0
            ? `${result.not_found.length} not found`
            : undefined,
      });
    },
    onError: () =>
      toast({ title: "Bulk delete failed", variant: "destructive" }),
  });

  const onDrop = useCallback(
    (accepted: File[]) => {
      if (!accepted.length) return;
      if (quotaFull) {
        toast({
          title: "Storage limit reached",
          description: "Delete documents to free space before uploading.",
          variant: "destructive",
        });
        return;
      }
      upload.mutate(accepted);
    },
    [upload, quotaFull],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    disabled: quotaFull,
  });

  useEffect(() => {
    function onPaste(e: ClipboardEvent) {
      if (quotaFull) return;
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
  }, [upload, quotaFull]);

  const visibleIds = docs.data?.map((d) => d.id) ?? [];
  const allSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selected.has(id));
  const someSelected = visibleIds.some((id) => selected.has(id));

  function toggleAll() {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(visibleIds));
    }
  }

  function toggleOne(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function confirmBulkDelete() {
    const ids = Array.from(selected);
    if (!ids.length) return;
    if (
      !window.confirm(
        `Delete ${ids.length} selected document(s)? This cannot be undone.`,
      )
    ) {
      return;
    }
    bulkDel.mutate(ids);
  }

  async function openDoc(d: LibraryDocument, inline: boolean) {
    try {
      await api.openLibraryDocument(d.id, d.filename, inline);
    } catch {
      toast({ title: "Could not load file", variant: "destructive" });
    }
  }

  const usedPct = quota.data
    ? Math.min(100, (quota.data.used_bytes / quota.data.limit_bytes) * 100)
    : 0;

  return (
    <AppShell>
      <main className="mx-auto max-w-4xl px-4 py-6 sm:px-6">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="mb-1 font-display text-2xl font-semibold tracking-tight">
              Documents
            </h1>
            <p className="text-sm text-muted-foreground">
              Your global document library. Everything uploaded here is indexed so
              the assistant can find and correlate it with tenders and projects.
            </p>
          </div>

          {quota.data && (
            <div className="shrink-0 text-right">
              <p
                className={cn(
                  "text-sm font-medium tabular-nums",
                  quotaFull && "text-gap",
                )}
              >
                {(quota.data.used_bytes / (1024 * 1024)).toFixed(1)} /{" "}
                {Math.round(quota.data.limit_bytes / (1024 * 1024))} MB
              </p>
              <div className="mt-1.5 ml-auto h-1.5 w-28 overflow-hidden rounded-full bg-muted">
                <div
                  className={cn(
                    "h-full rounded-full transition-all duration-300",
                    usedPct >= 95
                      ? "bg-gap"
                      : usedPct >= 80
                        ? "bg-verify"
                        : "bg-teal",
                  )}
                  style={{ width: `${usedPct}%` }}
                />
              </div>
            </div>
          )}
        </div>

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Select
            value={sort}
            onValueChange={(v) => setSort(v as SortOption)}
          >
            <SelectTrigger className="h-9 w-[160px] text-xs">
              <SelectValue placeholder="Sort by" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="newest">Newest first</SelectItem>
              <SelectItem value="oldest">Oldest first</SelectItem>
              <SelectItem value="name">Name A–Z</SelectItem>
            </SelectContent>
          </Select>

          <Select value={projectFilter} onValueChange={setProjectFilter}>
            <SelectTrigger className="h-9 w-[180px] text-xs">
              <SelectValue placeholder="All projects" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All documents</SelectItem>
              <SelectItem value="unlinked">Not linked to a project</SelectItem>
              {projects.data?.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {someSelected && (
            <Button
              size="sm"
              variant="destructive"
              className="ml-auto h-9 gap-1.5 text-xs"
              onClick={confirmBulkDelete}
              disabled={bulkDel.isPending}
            >
              {bulkDel.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Trash2 className="h-3.5 w-3.5" />
              )}
              Delete selected ({selected.size})
            </Button>
          )}
        </div>

        {visibleIds.length > 0 && (
          <label className="mb-3 flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
            <Checkbox
              checked={allSelected}
              onCheckedChange={toggleAll}
              aria-label="Select all documents"
            />
            Select all on this page
          </label>
        )}

        <div
          {...getRootProps()}
          className={cn(
            "mb-3 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-border bg-card/60 px-4 py-10 text-center transition-all hover:border-teal/40 hover:bg-accent/40",
            isDragActive && "border-teal bg-teal/5 shadow-soft",
            quotaFull && "cursor-not-allowed opacity-60 hover:border-border hover:bg-card/60",
          )}
        >
          <input {...getInputProps()} disabled={quotaFull} />
          <div className="flex h-11 w-11 items-center justify-center rounded-full bg-accent">
            <UploadCloud className="h-5 w-5 text-accent-foreground" />
          </div>
          <p className="text-sm">
            {quotaFull
              ? "Storage full — delete documents to upload more"
              : "Drop PDFs, images, Word/PowerPoint docs, Excel, or zips here, or click to browse."}
          </p>
          {!quotaFull && (
            <p className="text-xs text-muted-foreground">
              You can also paste a screenshot anywhere on this page.
            </p>
          )}
        </div>

        {libraryUpload && (
          <div className="mb-6 space-y-1">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>
                {(libraryUpload.percent ?? 0) < 100
                  ? "Uploading…"
                  : "Processing upload…"}
              </span>
              <span>{libraryUpload.percent ?? 0}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-teal transition-all duration-200"
                style={{ width: `${libraryUpload.percent ?? 0}%` }}
              />
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {docs.data?.map((d) => (
            <div
              key={d.id}
              className={cn(
                "flex flex-col rounded-xl border border-border/60 bg-card p-3 shadow-soft",
                selected.has(d.id) && "ring-2 ring-teal/40",
              )}
            >
              <div className="flex items-start gap-2">
                <Checkbox
                  className="mt-1"
                  checked={selected.has(d.id)}
                  onCheckedChange={() => toggleOne(d.id)}
                  aria-label={`Select ${d.filename}`}
                />
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
                    {d.size_bytes != null && d.size_bytes > 0 && (
                      <span className="text-xs text-muted-foreground">
                        {formatBytes(d.size_bytes)}
                      </span>
                    )}
                  </div>
                  {d.created_at && (
                    <p className="mt-0.5 text-[10px] text-muted-foreground">
                      {new Date(d.created_at).toLocaleString()}
                    </p>
                  )}
                  {d.projects && d.projects.length > 0 && (
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      <FolderOpen className="h-3 w-3 text-muted-foreground" />
                      {d.projects.map((p) => (
                        <Badge
                          key={p.id}
                          variant="secondary"
                          className="text-[10px] font-normal"
                        >
                          {p.name}
                        </Badge>
                      ))}
                    </div>
                  )}
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

              <div className="mt-2 flex items-center gap-1 border-t border-border/40 pt-2 pl-6">
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

        {docs.data?.length === 0 && !docs.isLoading && (
          <div className="rounded-2xl border border-dashed border-border py-12 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
              <FileText className="h-5 w-5 text-muted-foreground" />
            </div>
            <p className="text-sm font-medium">
              {projectFilter !== "all"
                ? "No documents match this filter"
                : "No documents yet"}
            </p>
            <p className="mx-auto mt-1 max-w-xs text-xs text-muted-foreground">
              {projectFilter !== "all"
                ? "Try a different project filter or upload new files."
                : "Upload past quotations, BOMs, contracts, photos — anything you want the assistant to know about."}
            </p>
          </div>
        )}
      </main>
    </AppShell>
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
    <div className="mt-2 space-y-2 border-t border-border/40 pt-2 pl-6">
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
