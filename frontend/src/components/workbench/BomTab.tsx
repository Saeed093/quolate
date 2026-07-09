"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, ClipboardPaste, Loader2, Sparkles } from "lucide-react";
import { api, type BomItem, type HsClassificationResult } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { toast } from "@/components/ui/use-toast";
import { parseBomTsv } from "@/lib/tsv";

export function BomTab({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const [pasteText, setPasteText] = useState("");
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

  const paste = useMutation({
    mutationFn: (text: string) => api.pasteBom(projectId, text),
    onSuccess: (rows) => {
      setPasteText("");
      invalidateBom();
      toast({ title: `Imported ${rows.length} BOM line(s)` });
    },
  });

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

  const preview = pasteText.trim() ? parseBomTsv(pasteText) : [];

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
      {autoBomFromQuotes && (bom.data?.length ?? 0) > 0 && (
        <div className="lg:col-span-2 rounded-xl border border-teal/30 bg-teal/5 px-4 py-3 text-sm text-muted-foreground">
          BOM lines were auto-generated from uploaded quotations. Review names,
          specs, and quantities below — edit anything that looks wrong.
        </div>
      )}
      <div className="space-y-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <ClipboardPaste className="h-4 w-4" /> Paste from Excel
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Textarea
              placeholder="Paste tab-separated rows (part, spec, qty, target price, notes)"
              value={pasteText}
              onChange={(e) => setPasteText(e.target.value)}
              onPaste={(e) => {
                const text = e.clipboardData.getData("text");
                if (text) setPasteText(text);
              }}
              rows={4}
            />
            {preview.length > 0 && (
              <p className="text-xs text-muted-foreground">
                {preview.length} row(s) detected — first: {preview[0].part_name}
              </p>
            )}
            <Button
              size="sm"
              disabled={!pasteText.trim() || paste.isPending}
              onClick={() => paste.mutate(pasteText)}
            >
              Import {preview.length > 0 ? `${preview.length} rows` : ""}
            </Button>
          </CardContent>
        </Card>

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
  return (
    <tr className="border-t border-border">
      <td className="px-2 py-1 text-muted-foreground">{item.line_no}</td>
      <EditableCell
        value={item.part_name}
        onSave={(v) => onSave({ part_name: v })}
      />
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
      <HsCodeCell projectId={projectId} item={item} onSave={onSave} />
      <td className="px-2 py-1">
        <Button variant="ghost" size="icon" onClick={onDelete} aria-label="Delete row">
          <Trash2 className="h-4 w-4" />
        </Button>
      </td>
    </tr>
  );
}

function HsCodeCell({
  projectId,
  item,
  onSave,
}: {
  projectId: string;
  item: BomItem;
  onSave: (patch: Partial<BomItem>) => void;
}) {
  const [local, setLocal] = useState(item.hs_code ?? "");
  const [open, setOpen] = useState(false);

  const suggest = useMutation({
    mutationFn: () => api.classifyBomHs(projectId, item.id),
    onSuccess: (result: HsClassificationResult) => {
      if (!result.candidates.length) {
        toast({ title: "No HS code suggestions for this line" });
        return;
      }
      setOpen(true);
    },
    onError: () =>
      toast({
        title: "HS suggestion failed — is the AI model running?",
        variant: "destructive",
      }),
  });

  function apply(code: string) {
    setLocal(code);
    setOpen(false);
    onSave({ hs_code: code });
  }

  return (
    <td className="px-1 py-1">
      <div className="flex items-center gap-1">
        <input
          className="w-full rounded bg-transparent px-1 py-1 font-data text-sm outline-none focus:bg-muted"
          placeholder="e.g. 8525.89.00"
          value={local}
          onChange={(e) => setLocal(e.target.value)}
          onBlur={() => {
            const v = local.trim();
            if (v !== (item.hs_code ?? "")) onSave({ hs_code: v || null });
          }}
        />
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0"
              title="Suggest HS code (AI)"
              disabled={suggest.isPending}
              onClick={(e) => {
                e.preventDefault();
                suggest.mutate();
              }}
            >
              {suggest.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Sparkles className="h-3.5 w-3.5" />
              )}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-80 text-sm" align="end">
            <p className="mb-2 text-xs font-semibold">
              AI-suggested HS codes — verify before relying on them
            </p>
            <div className="flex flex-col gap-1.5">
              {(suggest.data?.candidates ?? []).map((c) => (
                <button
                  key={c.hs_code}
                  type="button"
                  className="rounded-md border border-border px-2 py-1.5 text-left transition-colors hover:bg-muted"
                  onClick={() => apply(c.hs_code)}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-data font-semibold">{c.hs_code}</span>
                    <span className="text-xs text-muted-foreground">
                      {Math.round(c.confidence * 100)}%
                    </span>
                  </div>
                  {c.reasoning && (
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      {c.reasoning}
                    </div>
                  )}
                </button>
              ))}
            </div>
          </PopoverContent>
        </Popover>
      </div>
    </td>
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
