"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { api, type ExtractedField } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { toast } from "@/components/ui/use-toast";
import { useAuthedImage } from "@/lib/useAuthedImage";
import { cn } from "@/lib/utils";

export function ReviewSplitView({
  documentId,
  projectId,
  onClose,
}: {
  documentId: string;
  projectId: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const review = useQuery({
    queryKey: ["review", documentId],
    queryFn: () => api.reviewDocument(documentId),
  });

  const fields = review.data?.fields ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState("");

  const flagged = useMemo(
    () => fields.filter((f) => f.status === "auto"),
    [fields],
  );
  const navList = flagged.length > 0 ? flagged : fields;

  useEffect(() => {
    if (!selectedId && navList.length > 0) setSelectedId(navList[0].id);
  }, [navList, selectedId]);

  const selected = fields.find((f) => f.id === selectedId) ?? null;
  const page = selected?.provenance?.page ?? 1;
  const pageUrl = review.data
    ? api.pageImageUrl(documentId, Math.max(1, page))
    : null;
  const { src, loading } = useAuthedImage(pageUrl);

  const doc = review.data?.document;
  const hasError = !!doc?.error;
  const docStatus = doc?.status ?? "";
  // Show "Mark as done" only when the document is in a reviewable state and
  // either all fields are confirmed/edited/rejected, or there are no fields.
  const pendingReview = docStatus === "needs_review" || docStatus === "failed";
  const allFieldsDone =
    fields.length === 0 ||
    fields.every(
      (f) => f.status === "confirmed" || f.status === "edited" || f.status === "rejected",
    );
  const showMarkDone = pendingReview && allFieldsDone;

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["review", documentId] });
    qc.invalidateQueries({ queryKey: ["documents", projectId] });
    qc.invalidateQueries({ queryKey: ["matrix", projectId] });
  };

  const save = useMutation({
    mutationFn: (patch: Partial<ExtractedField>) =>
      api.updateField(selected!.id, patch),
    onSuccess: invalidate,
  });

  const markDone = useMutation({
    mutationFn: () => api.markReviewed(documentId),
    onSuccess: () => {
      invalidate();
      toast({ title: "Document marked as reviewed" });
      onClose();
    },
    onError: () => toast({ title: "Could not mark as reviewed", variant: "destructive" }),
  });

  const reparse = useMutation({
    mutationFn: () => api.reparseDocument(documentId),
    onSuccess: () => {
      invalidate();
      toast({ title: "Re-parsing document…" });
      onClose();
    },
    onError: () => toast({ title: "Could not re-parse", variant: "destructive" }),
  });

  function confirmField() {
    if (selected) save.mutate({ status: "confirmed" });
    gotoNext();
  }
  function startEdit() {
    if (!selected) return;
    setEditing(true);
    setEditValue(selected.value_num ?? selected.value_text ?? "");
  }
  function commitEdit() {
    if (!selected) return;
    const asNum = Number(editValue);
    const patch: Partial<ExtractedField> = Number.isNaN(asNum)
      ? { value_text: editValue, status: "edited" }
      : { value_num: editValue, status: "edited" };
    save.mutate(patch);
    setEditing(false);
  }
  function gotoNext() {
    const idx = navList.findIndex((f) => f.id === selectedId);
    const next = navList[Math.min(idx + 1, navList.length - 1)];
    if (next) setSelectedId(next.id);
  }
  function gotoPrev() {
    const idx = navList.findIndex((f) => f.id === selectedId);
    const prev = navList[Math.max(idx - 1, 0)];
    if (prev) setSelectedId(prev.id);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (editing) {
      if (e.key === "Enter") {
        e.preventDefault();
        commitEdit();
      }
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      confirmField();
    } else if (e.key.toLowerCase() === "e") {
      e.preventDefault();
      startEdit();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      gotoNext();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      gotoPrev();
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        className="grid h-[90vh] w-[95vw] max-w-6xl grid-rows-[auto_1fr] gap-4 sm:h-[85vh] sm:w-[90vw]"
        onKeyDown={onKeyDown}
      >
        <DialogHeader>
          <div className="flex items-center justify-between gap-3">
            <DialogTitle className="truncate">
              {doc?.original_filename ?? "Review"}
            </DialogTitle>
            <div className="flex shrink-0 items-center gap-2">
              {hasError && (
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1.5"
                  disabled={reparse.isPending}
                  onClick={() => reparse.mutate()}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Retry parsing
                </Button>
              )}
              {showMarkDone && (
                <Button
                  size="sm"
                  disabled={markDone.isPending}
                  onClick={() => markDone.mutate()}
                >
                  Mark as done
                </Button>
              )}
            </div>
          </div>
          {hasError && (
            <p className="mt-1 text-xs text-destructive">{doc!.error}</p>
          )}
        </DialogHeader>
        <div className="grid min-h-0 grid-rows-[minmax(0,2fr)_minmax(0,3fr)] gap-4 md:grid-cols-2 md:grid-rows-1">
          <div className="relative overflow-auto rounded-xl border border-border/60 bg-muted/30">
            {loading && (
              <p className="p-4 text-sm text-muted-foreground">Loading page…</p>
            )}
            {src && (
              <PageWithBox src={src} bbox={selected?.provenance?.bbox ?? null} />
            )}
            {!src && !loading && (
              <p className="p-4 text-sm text-muted-foreground">
                No page image available for this document.
              </p>
            )}
          </div>

          <div className="flex min-h-0 flex-col">
            <p className="mb-2 text-xs text-muted-foreground">
              Enter = confirm · E = edit · ↑ ↓ = move · {flagged.length} flagged
            </p>
            <div className="min-h-0 flex-1 space-y-2 overflow-auto pr-1">
              {navList.map((f) => (
                <div
                  key={f.id}
                  onClick={() => setSelectedId(f.id)}
                  className={cn(
                    "cursor-pointer rounded-xl border bg-card p-3 transition-all",
                    f.id === selectedId
                      ? "border-teal shadow-card ring-2 ring-teal/20"
                      : "border-border/60 hover:border-teal/30",
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{f.field_type}</span>
                    <FieldStatus field={f} />
                  </div>
                  {editing && f.id === selectedId ? (
                    <div className="mt-2 flex gap-2">
                      <Input
                        autoFocus
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                      />
                      <Button size="sm" onClick={commitEdit}>
                        Save
                      </Button>
                    </div>
                  ) : (
                    <div className="mt-1 text-sm">
                      {f.value_num ?? f.value_text ?? "—"}
                      {f.unit ? ` ${f.unit}` : ""}
                    </div>
                  )}
                  {f.provenance?.source_snippet && (
                    <div className="mt-1 text-xs italic text-muted-foreground">
                      “{f.provenance.source_snippet}”
                    </div>
                  )}
                  {f.id === selectedId && !editing && (
                    <div className="mt-2 flex gap-2">
                      <Button size="sm" onClick={confirmField}>
                        Confirm
                      </Button>
                      <Button size="sm" variant="outline" onClick={startEdit}>
                        Edit
                      </Button>
                    </div>
                  )}
                </div>
              ))}
              {navList.length === 0 && (
                <div className="space-y-3 py-4 text-sm text-muted-foreground">
                  <p>No extracted fields.</p>
                  {hasError ? (
                    <p>
                      The LLM could not parse this document. Use{" "}
                      <strong>Retry parsing</strong> above to try again.
                    </p>
                  ) : (
                    <p>All fields have been reviewed.</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function FieldStatus({ field }: { field: ExtractedField }) {
  const conf = field.confidence ? Number(field.confidence) : null;
  if (field.status === "confirmed" || field.status === "edited")
    return <Badge variant="ok">{field.status}</Badge>;
  if (field.status === "rejected")
    return <Badge variant="gap">rejected</Badge>;
  return (
    <Badge variant="verify">
      auto{conf !== null ? ` ${Math.round(conf * 100)}%` : ""}
    </Badge>
  );
}

function PageWithBox({
  src,
  bbox,
}: {
  src: string;
  bbox: [number, number, number, number] | null;
}) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);

  const overlay =
    bbox && dims
      ? {
          left: `${(bbox[0] / dims.w) * 100}%`,
          top: `${(bbox[1] / dims.h) * 100}%`,
          width: `${((bbox[2] - bbox[0]) / dims.w) * 100}%`,
          height: `${((bbox[3] - bbox[1]) / dims.h) * 100}%`,
        }
      : null;

  return (
    <div className="relative inline-block">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        ref={imgRef}
        src={src}
        alt="Document page"
        className="max-w-full"
        onLoad={(e) =>
          setDims({
            w: e.currentTarget.naturalWidth,
            h: e.currentTarget.naturalHeight,
          })
        }
      />
      {overlay && (
        <div
          className="pointer-events-none absolute border-2 border-verify bg-verify/20"
          style={overlay}
        />
      )}
    </div>
  );
}
