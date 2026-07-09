"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UploadCloud, FileText, Library, X, RotateCcw } from "lucide-react";
import { api, type Document, type LibraryDocument } from "@/lib/api";
import { useActivity } from "@/contexts/ActivityContext";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/use-toast";
import { cn } from "@/lib/utils";
import { ReviewSplitView } from "@/components/workbench/ReviewSplitView";

const STATUS_VARIANT: Record<string, "ok" | "verify" | "gap" | "secondary"> = {
  parsed: "ok",
  needs_review: "verify",
  failed: "gap",
  pending: "secondary",
  processing: "secondary",
};

export function InboxTab({
  projectId,
  openDocId,
  onConsumeOpen,
}: {
  projectId: string;
  openDocId: string | null;
  onConsumeOpen: () => void;
}) {
  const qc = useQueryClient();
  const { startUpload, endUpload } = useActivity();
  const uploadId = `project-${projectId}`;
  const [reviewDocId, setReviewDocId] = useState<string | null>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [libraryFilter, setLibraryFilter] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const notifiedAutoBom = useRef<Set<string>>(new Set());

  const docs = useQuery({
    queryKey: ["documents", projectId],
    queryFn: () => api.listDocuments(projectId),
    refetchInterval: (q) => {
      const data = q.state.data as Document[] | undefined;
      const busy = data?.some((d) =>
        ["pending", "processing"].includes(d.status),
      );
      return busy ? 2000 : false;
    },
  });

  const reparse = useMutation({
    mutationFn: (docId: string) => api.reparseDocument(docId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["documents", projectId] });
      qc.invalidateQueries({ queryKey: ["activity"] });
      toast({ title: "Re-parsing document…" });
    },
    onError: () =>
      toast({ title: "Could not re-parse", variant: "destructive" }),
  });

  const reparseAll = useMutation({
    mutationFn: () => api.reparseAllDocuments(projectId),
    onSuccess: (requeued) => {
      qc.invalidateQueries({ queryKey: ["documents", projectId] });
      qc.invalidateQueries({ queryKey: ["activity"] });
      qc.invalidateQueries({ queryKey: ["matrix", projectId] });
      toast({
        title: requeued.length
          ? `Re-extracting ${requeued.length} document(s)…`
          : "No documents to re-extract",
      });
    },
    onError: () =>
      toast({ title: "Could not re-extract documents", variant: "destructive" }),
  });

  const upload = useMutation({
    mutationFn: ({ files, kind }: { files: File[]; kind?: string }) => {
      startUpload(uploadId, `Uploading ${files.length} file(s)…`);
      return api.uploadDocuments(projectId, files, kind);
    },
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ["documents", projectId] });
      qc.invalidateQueries({ queryKey: ["activity"] });
      toast({ title: `Uploaded ${created.length} file(s)` });
    },
    onError: () => toast({ title: "Upload failed", variant: "destructive" }),
    onSettled: () => endUpload(uploadId),
  });

  const onDrop = useCallback(
    (accepted: File[]) => {
      if (accepted.length) upload.mutate({ files: accepted });
    },
    [upload],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop });

  // ---- Library attach ----
  const linkedDocs = useQuery({
    queryKey: ["project-library-documents", projectId],
    queryFn: () => api.listProjectLibraryDocuments(projectId),
  });

  const libraryDocs = useQuery({
    queryKey: ["library-documents"],
    queryFn: () => api.listLibraryDocuments(),
    enabled: libraryOpen,
  });

  const attach = useMutation({
    mutationFn: async (ids: string[]) => {
      for (const id of ids) {
        await api.linkLibraryDocument(projectId, id);
      }
      return ids.length;
    },
    onSuccess: (count) => {
      qc.invalidateQueries({ queryKey: ["project-library-documents", projectId] });
      setLibraryOpen(false);
      setSelected(new Set());
      toast({ title: `Attached ${count} document(s) from library` });
    },
    onError: () => toast({ title: "Attach failed", variant: "destructive" }),
  });

  const unlink = useMutation({
    mutationFn: (linkId: string) => api.unlinkLibraryDocument(projectId, linkId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-library-documents", projectId] });
      toast({ title: "Removed from project" });
    },
  });

  const alreadyLinked = useMemo(
    () => new Set((linkedDocs.data ?? []).map((l) => l.library_document_id)),
    [linkedDocs.data],
  );

  const filteredLibrary = useMemo(() => {
    const q = libraryFilter.trim().toLowerCase();
    return (libraryDocs.data ?? []).filter(
      (d: LibraryDocument) =>
        !q || d.filename.toLowerCase().includes(q) || d.kind.toLowerCase().includes(q),
    );
  }, [libraryDocs.data, libraryFilter]);

  // Global paste handler: paste an image (e.g. screenshot) -> upload as screenshot.
  useEffect(() => {
    function onPaste(e: ClipboardEvent) {
      const files: File[] = [];
      for (const item of Array.from(e.clipboardData?.items ?? [])) {
        if (item.kind === "file" && item.type.startsWith("image/")) {
          const f = item.getAsFile();
          if (f) files.push(f);
        }
      }
      if (files.length) upload.mutate({ files, kind: "screenshot" });
    }
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [upload]);

  useEffect(() => {
    if (openDocId) {
      setReviewDocId(openDocId);
      onConsumeOpen();
    }
  }, [openDocId, onConsumeOpen]);

  // When a document finishes parsing it produces quotes/fields that feed the
  // matrix, so refresh the matrix as parsed documents appear.
  const parsedCount = useMemo(
    () =>
      (docs.data ?? []).filter((d) =>
        ["parsed", "needs_review"].includes(d.status),
      ).length,
    [docs.data],
  );
  useEffect(() => {
    qc.invalidateQueries({ queryKey: ["matrix", projectId] });
    qc.invalidateQueries({ queryKey: ["bom", projectId] });
  }, [parsedCount, projectId, qc]);

  // Toast once when a document auto-creates BOM lines from a quotation.
  useEffect(() => {
    for (const d of docs.data ?? []) {
      const n = d.auto_bom_created ?? 0;
      if (n > 0 && !notifiedAutoBom.current.has(d.id)) {
        notifiedAutoBom.current.add(d.id);
        toast({
          title: `Created ${n} BOM line(s) from ${d.original_filename}`,
          description: "Open the BOM or Matrix tab to review.",
        });
      }
    }
  }, [docs.data]);

  const grouped = useMemo(() => groupBySupplier(docs.data ?? []), [docs.data]);

  return (
    <div className="space-y-4">
      <div
        {...getRootProps()}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-border bg-card/60 px-4 py-10 text-center transition-all hover:border-teal/40 hover:bg-accent/40",
          isDragActive && "border-teal bg-teal/5 shadow-soft",
        )}
      >
        <input {...getInputProps()} />
        <div className="flex h-11 w-11 items-center justify-center rounded-full bg-accent">
          <UploadCloud className="h-5 w-5 text-accent-foreground" />
        </div>
        <p className="text-sm">
          Drop vendor quotations here — BOM lines are created automatically when
          your project has none yet.
        </p>
        <p className="text-xs text-muted-foreground">
          You can also paste a screenshot anywhere on this page.
        </p>
      </div>

      <div className="flex justify-end gap-2">
        {(docs.data?.length ?? 0) > 0 && (
          <Button
            size="sm"
            variant="outline"
            className="gap-1.5"
            disabled={
              reparseAll.isPending ||
              docs.data?.some((d) =>
                ["pending", "processing"].includes(d.status),
              )
            }
            onClick={() => reparseAll.mutate()}
            title="Re-run extraction on every document (picks up prices, MOQ, lead time and incoterms)"
          >
            <RotateCcw className="h-4 w-4" />
            Re-extract all
          </Button>
        )}
        <Button
          size="sm"
          variant="outline"
          onClick={() => setLibraryOpen(true)}
          className="gap-1.5"
        >
          <Library className="h-4 w-4" />
          Add from library
        </Button>
      </div>

      {/* Library docs linked to this project */}
      {(linkedDocs.data?.length ?? 0) > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-muted-foreground">
            From library
          </h3>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {linkedDocs.data!.map((l) => (
              <div
                key={l.id}
                className="flex items-start gap-3 rounded-xl border border-border/60 bg-card p-3 shadow-soft"
              >
                <Library className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium" title={l.filename}>
                    {l.filename}
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <Badge variant="secondary">from library</Badge>
                    <Badge variant={STATUS_VARIANT[l.status] ?? "secondary"}>
                      {l.status.replace("_", " ")}
                    </Badge>
                    <span className="text-xs text-muted-foreground">{l.kind}</span>
                  </div>
                </div>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-6 w-6 shrink-0"
                  onClick={() => unlink.mutate(l.id)}
                  aria-label="Remove from project"
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}

      {grouped.map(([supplierLabel, items]) => (
        <div key={supplierLabel}>
          <h3 className="mb-2 text-sm font-semibold text-muted-foreground">
            {supplierLabel}
          </h3>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {items.map((d) => (
              <div
                key={d.id}
                className="card-interactive flex items-start gap-3 rounded-xl border border-border/60 bg-card p-3 shadow-soft"
              >
                <button
                  type="button"
                  onClick={() => setReviewDocId(d.id)}
                  className="flex min-w-0 flex-1 items-start gap-3 text-left"
                >
                  <FileText className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">
                      {d.original_filename}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      <Badge variant={STATUS_VARIANT[d.status] ?? "secondary"}>
                        {d.status.replace("_", " ")}
                      </Badge>
                      {(d.auto_bom_created ?? 0) > 0 && (
                        <Badge variant="ok">+{d.auto_bom_created} BOM</Badge>
                      )}
                      <span className="text-xs text-muted-foreground">{d.kind}</span>
                    </div>
                    {d.error && (
                      <div className="mt-1 truncate text-xs text-gap">{d.error}</div>
                    )}
                  </div>
                </button>
                {(d.status === "failed" ||
                  (d.status === "needs_review" && d.error)) && (
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-8 w-8 shrink-0"
                    aria-label="Retry parsing"
                    disabled={reparse.isPending}
                    onClick={(e) => {
                      e.stopPropagation();
                      reparse.mutate(d.id);
                    }}
                  >
                    <RotateCcw className="h-4 w-4" />
                  </Button>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}

      {docs.data?.length === 0 && (
        <p className="text-sm text-muted-foreground">No documents uploaded yet.</p>
      )}

      {reviewDocId && (
        <ReviewSplitView
          documentId={reviewDocId}
          projectId={projectId}
          onClose={() => setReviewDocId(null)}
        />
      )}

      {/* Add-from-library dialog */}
      <Dialog open={libraryOpen} onOpenChange={setLibraryOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Add documents from your library</DialogTitle>
          </DialogHeader>
          <Input
            placeholder="Filter by filename or kind..."
            value={libraryFilter}
            onChange={(e) => setLibraryFilter(e.target.value)}
          />
          <div className="max-h-72 space-y-1 overflow-auto">
            {filteredLibrary.map((d) => {
              const linked = alreadyLinked.has(d.id);
              return (
                <label
                  key={d.id}
                  className={cn(
                    "flex cursor-pointer items-center gap-3 rounded-md border border-border p-2",
                    linked && "opacity-50",
                  )}
                >
                  <Checkbox
                    checked={linked || selected.has(d.id)}
                    disabled={linked}
                    onCheckedChange={(checked) => {
                      setSelected((prev) => {
                        const next = new Set(prev);
                        if (checked) next.add(d.id);
                        else next.delete(d.id);
                        return next;
                      });
                    }}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm">{d.filename}</div>
                    <div className="text-xs text-muted-foreground">
                      {d.kind}
                      {linked ? " · already attached" : ""}
                    </div>
                  </div>
                </label>
              );
            })}
            {filteredLibrary.length === 0 && (
              <p className="py-4 text-center text-sm text-muted-foreground">
                {libraryDocs.isLoading
                  ? "Loading..."
                  : "No library documents. Upload some in the Documents tab."}
              </p>
            )}
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setLibraryOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={selected.size === 0 || attach.isPending}
              onClick={() => attach.mutate(Array.from(selected))}
            >
              {attach.isPending
                ? "Attaching..."
                : `Attach ${selected.size || ""} document(s)`}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function groupBySupplier(docs: Document[]): [string, Document[]][] {
  const map = new Map<string, Document[]>();
  for (const d of docs) {
    const key = d.supplier_id ?? "Unassigned";
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(d);
  }
  // Supplier ids aren't names here; label unassigned clearly, others generically.
  return Array.from(map.entries()).map(([k, v]) => [
    k === "Unassigned" ? "Unassigned" : "Supplier documents",
    v,
  ]);
}
