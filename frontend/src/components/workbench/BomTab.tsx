"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Loader2, Sparkles, Check, RefreshCw } from "lucide-react";
import { api, type BomItem, type HsCandidate } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function BomTab({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const [supplierName, setSupplierName] = useState("");

  const bom = useQuery({
    queryKey: ["bom", projectId],
    queryFn: () => api.listBom(projectId),
  });
  const suppliers = useQuery({
    queryKey: ["suppliers", projectId],
    queryFn: () => api.listSuppliers(projectId),
  });
  const documents = useQuery({
    queryKey: ["documents", projectId],
    queryFn: () => api.listDocuments(projectId),
  });
  const autoBomFromQuotes = (documents.data ?? []).some(
    (d) => (d.auto_bom_created ?? 0) > 0,
  );

  const invalidateBom = () => {
    qc.invalidateQueries({ queryKey: ["bom", projectId] });
    // BOM changes alter the matrix rows, so refresh it too.
    qc.invalidateQueries({ queryKey: ["matrix", projectId] });
  };

  const addRow = useMutation({
    mutationFn: () => api.createBom(projectId, { part_name: "New item" }),
    onSuccess: invalidateBom,
  });

  const del = useMutation({
    mutationFn: (id: string) => api.deleteBom(id),
    onSuccess: invalidateBom,
  });

  const update = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<BomItem> }) =>
      api.updateBom(id, patch),
    onSuccess: invalidateBom,
  });

  const addSupplier = useMutation({
    mutationFn: (name: string) => api.createSupplier(projectId, { name }),
    onSuccess: () => {
      setSupplierName("");
      qc.invalidateQueries({ queryKey: ["suppliers", projectId] });
      // A new supplier adds a matrix column.
      qc.invalidateQueries({ queryKey: ["matrix", projectId] });
    },
  });

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
      {autoBomFromQuotes && (bom.data?.length ?? 0) > 0 && (
        <div className="lg:col-span-2 rounded-xl border border-teal/30 bg-teal/5 px-4 py-3 text-sm text-muted-foreground">
          BOM lines were auto-generated from uploaded quotations. Review names,
          specs, and quantities below — edit anything that looks wrong.
        </div>
      )}
      <div className="space-y-4">
        <div className="overflow-x-auto rounded-xl border border-border/60 bg-card shadow-soft">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="w-10 px-2 py-2.5 font-semibold">#</th>
                <th className="px-2 py-2.5 font-semibold">Part</th>
                <th className="px-2 py-2.5 font-semibold">Spec</th>
                <th className="w-24 px-2 py-2.5 font-semibold">Qty</th>
                <th className="w-28 px-2 py-2.5 font-semibold">Target</th>
                <th className="w-40 px-2 py-2.5 font-semibold" title="Pakistan PCT/HS code — used for statutory duty in the matrix">
                  HS code
                </th>
                <th className="w-10 px-2 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {bom.data?.map((item) => (
                <BomRow
                  key={item.id}
                  projectId={projectId}
                  item={item}
                  onSave={(patch) => update.mutate({ id: item.id, patch })}
                  onDelete={() => del.mutate(item.id)}
                />
              ))}
              {bom.data?.length === 0 && (
                <tr>
                  <td
                    colSpan={7}
                    className="px-2 py-6 text-center text-muted-foreground"
                  >
                    No BOM lines yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <Button size="sm" variant="outline" onClick={() => addRow.mutate()}>
          <Plus className="h-4 w-4" /> Add line
        </Button>
      </div>

      <div className="space-y-3">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Suppliers</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (supplierName.trim()) addSupplier.mutate(supplierName.trim());
              }}
            >
              <Input
                placeholder="Supplier name"
                value={supplierName}
                onChange={(e) => setSupplierName(e.target.value)}
              />
              <Button type="submit" size="sm">
                Add
              </Button>
            </form>
            <div className="space-y-2">
              {suppliers.data?.map((s) => (
                <div
                  key={s.id}
                  className="rounded-md border border-border px-3 py-2 text-sm"
                >
                  <div className="font-medium">{s.name}</div>
                  {s.country && (
                    <div className="text-xs text-muted-foreground">{s.country}</div>
                  )}
                </div>
              ))}
              {suppliers.data?.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  Suppliers are also created automatically from uploaded quotes.
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function BomRow({
  projectId,
  item,
  onSave,
  onDelete,
}: {
  projectId: string;
  item: BomItem;
  onSave: (patch: Partial<BomItem>) => void;
  onDelete: () => void;
}) {
  const [hsLocal, setHsLocal] = useState(item.hs_code ?? "");

  // Generate HS-code candidates for every line as soon as the step opens, so a
  // selectable box of suggestions sits under each item. Cached per line so
  // switching steps doesn't re-run the model; "Regenerate" re-runs on demand.
  const suggest = useQuery({
    queryKey: ["hs-suggest", item.id],
    queryFn: () => api.classifyBomHs(projectId, item.id),
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
  });
  const candidates = suggest.data?.candidates ?? [];

  function commitHs(value: string) {
    const v = value.trim();
    if (v !== (item.hs_code ?? "")) onSave({ hs_code: v || null });
  }
  function applyCandidate(code: string) {
    setHsLocal(code);
    onSave({ hs_code: code });
  }

  return (
    <>
      <tr className="border-t border-border">
        <td className="px-2 py-2 align-top text-muted-foreground">{item.line_no}</td>
        <EditableCell value={item.part_name} onSave={(v) => onSave({ part_name: v })} />
        <EditableCell
          value={item.spec_requirement ?? ""}
          onSave={(v) => onSave({ spec_requirement: v || null })}
        />
        <EditableCell
          value={item.quantity ?? ""}
          onSave={(v) => onSave({ quantity: v || null })}
        />
        <EditableCell
          value={item.target_price ?? ""}
          onSave={(v) => onSave({ target_price: v || null })}
        />
        <td className="px-1 py-1.5 align-top">
          <div className="flex items-center gap-1">
            <input
              className="w-full rounded bg-transparent px-1 py-1 font-data text-sm outline-none focus:bg-muted"
              placeholder="e.g. 8525.89.00"
              value={hsLocal}
              onChange={(e) => setHsLocal(e.target.value)}
              onBlur={() => commitHs(hsLocal)}
            />
            {suggest.isFetching && (
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />
            )}
          </div>
        </td>
        <td className="px-2 py-1.5 align-top">
          <Button variant="ghost" size="icon" onClick={onDelete} aria-label="Delete row">
            <Trash2 className="h-4 w-4" />
          </Button>
        </td>
      </tr>
      <tr>
        <td colSpan={7} className="px-2 pb-3 pt-0">
          <HsCandidatesBox
            candidates={candidates}
            selected={hsLocal.trim()}
            isFetching={suggest.isFetching}
            isError={suggest.isError}
            onApply={applyCandidate}
            onRegenerate={() => suggest.refetch()}
          />
        </td>
      </tr>
    </>
  );
}

function HsCandidatesBox({
  candidates,
  selected,
  isFetching,
  isError,
  onApply,
  onRegenerate,
}: {
  candidates: HsCandidate[];
  selected: string;
  isFetching: boolean;
  isError: boolean;
  onApply: (code: string) => void;
  onRegenerate: () => void;
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-muted/30 p-2.5">
      <div className="mb-2 flex items-center justify-between">
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5 text-teal" />
          AI generated HS codes
          <span className="font-normal">— pick the best match</span>
        </span>
        <button
          type="button"
          onClick={onRegenerate}
          disabled={isFetching}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
        >
          <RefreshCw className={cn("h-3 w-3", isFetching && "animate-spin")} />
          Regenerate
        </button>
      </div>

      {isFetching && candidates.length === 0 ? (
        <div className="flex items-center gap-2 px-1 py-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Generating suggestions…
        </div>
      ) : candidates.length > 0 ? (
        <div className="grid gap-1.5 sm:grid-cols-2">
          {candidates.map((c) => {
            const isSel = c.hs_code === selected;
            return (
              <button
                key={c.hs_code}
                type="button"
                onClick={() => onApply(c.hs_code)}
                aria-pressed={isSel}
                title={c.reasoning ?? undefined}
                className={cn(
                  "flex items-start justify-between gap-2 rounded-md border px-2.5 py-2 text-left transition-colors",
                  isSel
                    ? "border-teal bg-teal/10"
                    : "border-border bg-card hover:border-teal/40 hover:bg-muted",
                )}
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-data text-sm font-semibold">{c.hs_code}</span>
                    {isSel && <Check className="h-3.5 w-3.5 shrink-0 text-teal" />}
                  </div>
                  {c.description && (
                    <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                      {c.description}
                    </div>
                  )}
                </div>
                <MatchBadge confidence={c.confidence} />
              </button>
            );
          })}
        </div>
      ) : isError ? (
        <div className="flex items-center justify-between gap-2 px-1 py-1.5 text-xs text-muted-foreground">
          <span>Couldn&apos;t reach the AI model — is it running?</span>
          <button
            type="button"
            onClick={onRegenerate}
            className="underline underline-offset-2 hover:text-foreground"
          >
            Retry
          </button>
        </div>
      ) : (
        <div className="px-1 py-1.5 text-xs text-muted-foreground">
          No HS-code suggestions for this line — type one in the field above.
        </div>
      )}
    </div>
  );
}

function MatchBadge({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const tone =
    confidence >= 0.75
      ? "bg-teal/15 text-teal"
      : confidence >= 0.5
        ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
        : "bg-muted text-muted-foreground";
  return (
    <span
      className={cn(
        "shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums",
        tone,
      )}
      title="AI confidence / match"
    >
      {pct}%
    </span>
  );
}

function EditableCell({
  value,
  onSave,
}: {
  value: string;
  onSave: (v: string) => void;
}) {
  const [local, setLocal] = useState(value);
  return (
    <td className="px-1 py-1">
      <input
        className="w-full rounded bg-transparent px-1 py-1 text-sm outline-none focus:bg-muted"
        value={local}
        onChange={(e) => setLocal(e.target.value)}
        onBlur={() => {
          if (local !== value) onSave(local);
        }}
      />
    </td>
  );
}
