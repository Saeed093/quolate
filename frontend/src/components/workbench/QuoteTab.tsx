"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FileText,
  Loader2,
  Sparkles,
  Plus,
  Trash2,
  FileSpreadsheet,
  FileDown,
  History,
  Lock,
} from "lucide-react";
import {
  api,
  type BomItem,
  type Quotation,
  type QuotationLine,
  type QuotationLineInput,
  type QuotationSourceRef,
  type QuotationVersion,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "@/components/ui/use-toast";

/**
 * Sell-side quotation workflow: extract requirements from RFP sources -> generate
 * a priced draft from the BOM/matrix -> review & edit (margin, GST, gaps) -> (later)
 * download the client DOCX + internal XLSX.
 */
export function QuoteTab({
  projectId,
  onGoToBom,
}: {
  projectId: string;
  onGoToBom?: () => void;
}) {
  const qc = useQueryClient();
  const [activeQuotationId, setActiveQuotationId] = useState<string | null>(null);

  const bom = useQuery({
    queryKey: ["bom", projectId],
    queryFn: () => api.listBom(projectId),
  });
  const quotations = useQuery({
    queryKey: ["quotations", projectId],
    queryFn: () => api.listQuotations(projectId),
  });

  const activeQuotation =
    quotations.data?.find((q) => q.id === activeQuotationId) ?? null;

  const generate = useMutation({
    mutationFn: () => api.createQuotation(projectId),
    onSuccess: (q) => {
      setActiveQuotationId(q.id);
      qc.invalidateQueries({ queryKey: ["quotations", projectId] });
      toast({ title: `Created ${q.quote_no}` });
    },
    onError: (err: Error) =>
      toast({ title: "Could not generate quotation", description: err.message, variant: "destructive" }),
  });

  const hasBom = (bom.data?.length ?? 0) > 0;

  return (
    <div className="space-y-6">
      <ExtractCard projectId={projectId} onGoToBom={onGoToBom} />

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center justify-between text-base">
            <span>Quotations</span>
            <Button
              size="sm"
              disabled={!hasBom || generate.isPending}
              onClick={() => generate.mutate()}
              title={hasBom ? "" : "Add requirements to the BOM first"}
            >
              {generate.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              Generate quotation
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {(quotations.data?.length ?? 0) === 0 ? (
            <p className="text-sm text-muted-foreground">
              No quotations yet. Add the customer&apos;s requirements to the BOM,
              then generate a priced draft.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {quotations.data?.map((q) => (
                <button
                  key={q.id}
                  type="button"
                  onClick={() => setActiveQuotationId(q.id)}
                  className={`rounded-lg border px-3 py-1.5 text-sm transition-colors ${
                    q.id === activeQuotationId
                      ? "border-teal bg-teal/10"
                      : "border-border hover:bg-muted"
                  }`}
                >
                  <span className="font-data">{q.quote_no}</span>
                  <span className="ml-2 text-xs text-muted-foreground">
                    v{q.versions.length} · {q.status}
                  </span>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {activeQuotation && (
        <QuotationReview
          key={activeQuotation.id}
          projectId={projectId}
          quotation={activeQuotation}
        />
      )}
    </div>
  );
}

// ---------- Extraction ----------
function ExtractCard({
  projectId,
  onGoToBom,
}: {
  projectId: string;
  onGoToBom?: () => void;
}) {
  const qc = useQueryClient();
  const [rfpText, setRfpText] = useState("");
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [extracted, setExtracted] = useState<BomItem[] | null>(null);

  const documents = useQuery({
    queryKey: ["documents", projectId],
    queryFn: () => api.listDocuments(projectId),
  });
  const parsedDocs = (documents.data ?? []).filter(
    (d) => d.status === "parsed" || d.status === "needs_review",
  );

  function toggleDoc(id: string) {
    setSelectedDocs((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const sources: QuotationSourceRef[] = [
    ...(rfpText.trim() ? [{ kind: "text" as const, text: rfpText.trim() }] : []),
    ...[...selectedDocs].map((id) => ({ kind: "document" as const, id })),
  ];

  const extract = useMutation({
    mutationFn: () => api.extractRequirements(projectId, sources),
    onSuccess: (items) => {
      setExtracted(items);
      qc.invalidateQueries({ queryKey: ["bom", projectId] });
      qc.invalidateQueries({ queryKey: ["matrix", projectId] });
      toast({ title: `Extracted ${items.length} requested item(s)` });
    },
    onError: (err: Error) =>
      toast({
        title: "Could not extract requirements",
        description: err.message.toLowerCase().includes("model")
          ? "Is the AI model running?"
          : err.message,
        variant: "destructive",
      }),
  });

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="h-4 w-4" /> Extract requirements from an RFP
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Textarea
          placeholder="Paste an email, WhatsApp message, or RFP text — e.g. &quot;Need 50 office chairs (ergonomic, mesh back) and 10 filing cabinets, delivered to Lahore by month end.&quot;"
          value={rfpText}
          onChange={(e) => setRfpText(e.target.value)}
          rows={4}
        />

        {parsedDocs.length > 0 && (
          <div className="space-y-2">
            <label className="text-xs font-medium text-muted-foreground">
              …or use an uploaded document
            </label>
            <div className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-border/60 p-2">
              {parsedDocs.map((d) => (
                <label
                  key={d.id}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted"
                >
                  <Checkbox
                    checked={selectedDocs.has(d.id)}
                    onCheckedChange={() => toggleDoc(d.id)}
                  />
                  <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate">{d.original_filename}</span>
                </label>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center gap-3">
          <Button
            disabled={sources.length === 0 || extract.isPending}
            onClick={() => extract.mutate()}
          >
            {extract.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Extracting…
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" /> Extract requirements
              </>
            )}
          </Button>
          <p className="text-xs text-muted-foreground">
            Images and scans are read via OCR.
          </p>
        </div>

        {extracted && (
          <div className="rounded-lg border border-teal/30 bg-teal/5 p-3 text-sm">
            Added {extracted.length} item(s) to the BOM.{" "}
            {onGoToBom && (
              <button
                type="button"
                className="font-medium text-teal underline"
                onClick={onGoToBom}
              >
                Review in BOM
              </button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------- Review & edit ----------
interface EditLine extends QuotationLine {
  _priceEdited?: boolean;
  _removed?: boolean;
  _isNew?: boolean;
}

function toPct(frac: string | undefined): string {
  if (frac === undefined || frac === null || frac === "") return "0";
  return String(Math.round(Number(frac) * 1000) / 10);
}
function fracFromPct(s: string): number {
  const n = Number(s);
  return Number.isNaN(n) ? 0 : n / 100;
}
function money(v: string | null, ccy: string): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return `${ccy} ${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function QuotationReview({
  projectId,
  quotation,
}: {
  projectId: string;
  quotation: Quotation;
}) {
  const qc = useQueryClient();
  const latest = quotation.versions[quotation.versions.length - 1];
  const [selectedVersionId, setSelectedVersionId] = useState(latest.id);
  const version: QuotationVersion =
    quotation.versions.find((v) => v.id === selectedVersionId) ?? latest;
  const ccy = version.currency;
  const isFinal = version.status === "final";

  const [marginPct, setMarginPct] = useState(toPct(version.margin_pct));
  const [gstEnabled, setGstEnabled] = useState(version.gst_enabled);
  const [gstPct, setGstPct] = useState(toPct(version.gst_pct));
  const [validity, setValidity] = useState(
    version.validity_days != null ? String(version.validity_days) : "",
  );
  const [lines, setLines] = useState<EditLine[]>(() =>
    version.lines.map((l) => ({ ...l })),
  );
  // After a successful save we ask how the user wants their finished quote.
  const [downloadPromptOpen, setDownloadPromptOpen] = useState(false);

  // Reset local state whenever the underlying version changes (e.g. after save).
  useEffect(() => {
    setMarginPct(toPct(version.margin_pct));
    setGstEnabled(version.gst_enabled);
    setGstPct(toPct(version.gst_pct));
    setValidity(version.validity_days != null ? String(version.validity_days) : "");
    setLines(version.lines.map((l) => ({ ...l })));
  }, [version]);

  const visibleLines = lines.filter((l) => !l._removed);

  // Live preview of totals (mirrors the backend math) so edits feel immediate.
  const preview = useMemo(() => {
    const marginFrac = fracFromPct(marginPct);
    let subtotal = 0;
    for (const l of visibleLines) {
      const qty = Number(l.qty ?? 1) || 1;
      let unitPrice: number | null;
      if (l.cost_source === "manual" || l._priceEdited) {
        unitPrice = l.unit_price != null && l.unit_price !== "" ? Number(l.unit_price) : null;
      } else if (l.unit_cost != null && l.unit_cost !== "") {
        unitPrice = Math.round(Number(l.unit_cost) * (1 + marginFrac));
      } else {
        unitPrice = null;
      }
      if (unitPrice != null) subtotal += unitPrice * qty;
    }
    const tax = gstEnabled ? Math.round(subtotal * fracFromPct(gstPct)) : 0;
    return { subtotal, tax, grand: subtotal + tax };
  }, [visibleLines, marginPct, gstEnabled, gstPct]);

  const gapCount = visibleLines.filter(
    (l) =>
      !(l.cost_source === "manual" || l._priceEdited) &&
      (l.unit_cost == null || l.unit_cost === ""),
  ).length;

  function patchLine(id: string, patch: Partial<EditLine>) {
    setLines((prev) => prev.map((l) => (l.id === id ? { ...l, ...patch } : l)));
  }
  function removeLine(id: string) {
    setLines((prev) =>
      prev
        .map((l) => (l.id === id ? { ...l, _removed: true } : l))
        .filter((l) => !(l._isNew && l.id === id)),
    );
  }
  function addLine() {
    const nextNo = Math.max(0, ...lines.map((l) => l.line_no)) + 1;
    setLines((prev) => [
      ...prev,
      {
        id: `new-${Date.now()}`,
        version_id: version.id,
        line_no: nextNo,
        description: "",
        spec: null,
        qty: "1",
        unit_cost: null,
        cost_source: "manual",
        unit_price: null,
        line_total: null,
        gap_flag: true,
        _isNew: true,
        _priceEdited: true,
      },
    ]);
  }

  const save = useMutation({
    mutationFn: () => {
      const lineInputs: QuotationLineInput[] = [];
      for (const l of lines) {
        if (l._removed && !l._isNew) {
          lineInputs.push({ id: l.id, remove: true });
        } else if (l._isNew && !l._removed) {
          lineInputs.push({
            description: l.description || "New item",
            spec: l.spec,
            qty: l.qty,
            unit_price: l.unit_price,
          });
        } else if (!l._removed) {
          lineInputs.push({
            id: l.id,
            description: l.description,
            spec: l.spec,
            qty: l.qty,
            ...(l._priceEdited ? { unit_price: l.unit_price } : {}),
          });
        }
      }
      return api.updateQuotationVersion(projectId, version.id, {
        margin_pct: fracFromPct(marginPct),
        gst_enabled: gstEnabled,
        gst_pct: fracFromPct(gstPct),
        validity_days: validity.trim() === "" ? null : Number(validity),
        lines: lineInputs,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["quotations", projectId] });
      toast({ title: "Quotation saved" });
      setDownloadPromptOpen(true);
    },
    onError: (err: Error) =>
      toast({ title: "Save failed", description: err.message, variant: "destructive" }),
  });

  const download = useMutation({
    mutationFn: (fmt: "docx" | "xlsx") =>
      api.downloadQuotationFile(
        projectId,
        version.id,
        fmt,
        `${quotation.quote_no}-v${version.version_no}.${fmt}`,
      ),
    onSuccess: () => setDownloadPromptOpen(false),
    onError: (err: Error) =>
      toast({ title: "Download failed", description: err.message, variant: "destructive" }),
  });

  const regenerate = useMutation({
    mutationFn: () => api.regenerateQuotationVersion(projectId, version.id),
    onSuccess: (v) => {
      setSelectedVersionId(v.id);
      qc.invalidateQueries({ queryKey: ["quotations", projectId] });
      toast({ title: `Created v${v.version_no}` });
    },
    onError: (err: Error) =>
      toast({ title: "Could not create version", description: err.message, variant: "destructive" }),
  });

  const finalize = useMutation({
    mutationFn: () => api.finalizeQuotationVersion(projectId, version.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["quotations", projectId] });
      toast({ title: "Quotation finalized" });
    },
    onError: (err: Error) =>
      toast({ title: "Could not finalize", description: err.message, variant: "destructive" }),
  });

  return (
    <Card>
      <CardHeader className="space-y-3 pb-3">
        <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-base">
          <span className="font-data">
            {quotation.quote_no}{" "}
            <span className="text-xs font-normal text-muted-foreground">
              v{version.version_no} · {version.status}
            </span>
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={download.isPending}
              title="Client-facing quotation (saved state)"
              onClick={() => download.mutate("docx")}
            >
              <FileDown className="h-4 w-4" /> DOCX
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={download.isPending}
              title="Internal calculation buildup (saved state)"
              onClick={() => download.mutate("xlsx")}
            >
              <FileSpreadsheet className="h-4 w-4" /> XLSX
            </Button>
          </div>
        </CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          {quotation.versions.map((v) => (
            <button
              key={v.id}
              type="button"
              onClick={() => setSelectedVersionId(v.id)}
              className={`rounded-md border px-2 py-1 text-xs transition-colors ${
                v.id === version.id
                  ? "border-teal bg-teal/10"
                  : "border-border hover:bg-muted"
              }`}
              title={v.status === "final" ? "Finalized" : "Draft"}
            >
              v{v.version_no}
              {v.status === "final" && " ✓"}
            </button>
          ))}
          <div className="ml-auto flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={regenerate.isPending}
              onClick={() => regenerate.mutate()}
              title="Create a new editable version from this one"
            >
              {regenerate.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <History className="h-4 w-4" />
              )}
              New version
            </Button>
            {!isFinal && (
              <Button
                size="sm"
                disabled={finalize.isPending}
                onClick={() => finalize.mutate()}
                title="Lock this version as final"
              >
                {finalize.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Lock className="h-4 w-4" />
                )}
                Finalize
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Settings */}
        <div className="flex flex-wrap items-end gap-4 rounded-xl border border-border/60 bg-card/70 p-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Margin %</span>
            <Input
              className="w-24"
              type="number"
              value={marginPct}
              disabled={isFinal}
              onChange={(e) => setMarginPct(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Validity (days)</span>
            <Input
              className="w-28"
              type="number"
              value={validity}
              disabled={isFinal}
              onChange={(e) => setValidity(e.target.value)}
            />
          </label>
          <label className="flex items-center gap-2 pb-2">
            <Checkbox
              checked={gstEnabled}
              disabled={isFinal}
              onCheckedChange={(v) => setGstEnabled(Boolean(v))}
            />
            <span className="text-sm">GST</span>
          </label>
          {gstEnabled && (
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">GST %</span>
              <Input
                className="w-24"
                type="number"
                value={gstPct}
                disabled={isFinal}
                onChange={(e) => setGstPct(e.target.value)}
              />
            </label>
          )}
        </div>

        {gapCount > 0 && (
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-sm">
            {gapCount} line(s) have no cost — type a unit price or remove them.
          </div>
        )}

        {/* Lines */}
        <div className="overflow-x-auto rounded-lg border border-border/60">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="w-10 px-2 py-2 font-semibold">#</th>
                <th className="px-2 py-2 font-semibold">Description</th>
                <th className="px-2 py-2 font-semibold">Spec</th>
                <th className="w-20 px-2 py-2 font-semibold">Qty</th>
                <th className="w-28 px-2 py-2 font-semibold">Unit cost</th>
                <th className="w-32 px-2 py-2 font-semibold">Unit price</th>
                <th className="w-28 px-2 py-2 font-semibold">Total</th>
                <th className="w-10 px-2 py-2" />
              </tr>
            </thead>
            <tbody>
              {visibleLines.map((l) => {
                const qty = Number(l.qty ?? 1) || 1;
                const derived =
                  l.unit_cost != null && l.unit_cost !== ""
                    ? Math.round(Number(l.unit_cost) * (1 + fracFromPct(marginPct)))
                    : null;
                const manual = l.cost_source === "manual" || l._priceEdited;
                const unitPrice = manual
                  ? l.unit_price != null && l.unit_price !== ""
                    ? Number(l.unit_price)
                    : null
                  : derived;
                const total = unitPrice != null ? unitPrice * qty : null;
                const isGap =
                  !manual && (l.unit_cost == null || l.unit_cost === "");
                return (
                  <tr
                    key={l.id}
                    className={`border-t border-border ${isGap ? "bg-amber-500/5" : ""}`}
                  >
                    <td className="px-2 py-1 text-muted-foreground">{l.line_no}</td>
                    <td className="px-1 py-1">
                      <input
                        className="w-full rounded bg-transparent px-1 py-1 outline-none focus:bg-muted"
                        value={l.description}
                        disabled={isFinal}
                        onChange={(e) => patchLine(l.id, { description: e.target.value })}
                      />
                    </td>
                    <td className="px-1 py-1">
                      <input
                        className="w-full rounded bg-transparent px-1 py-1 text-muted-foreground outline-none focus:bg-muted"
                        value={l.spec ?? ""}
                        disabled={isFinal}
                        onChange={(e) => patchLine(l.id, { spec: e.target.value || null })}
                      />
                    </td>
                    <td className="px-1 py-1">
                      <input
                        className="w-full rounded bg-transparent px-1 py-1 outline-none focus:bg-muted"
                        type="number"
                        value={l.qty ?? ""}
                        disabled={isFinal}
                        onChange={(e) => patchLine(l.id, { qty: e.target.value })}
                      />
                    </td>
                    <td className="px-2 py-1 text-muted-foreground">
                      {money(l.unit_cost, ccy)}
                    </td>
                    <td className="px-1 py-1">
                      <input
                        className="w-full rounded bg-transparent px-1 py-1 outline-none focus:bg-muted"
                        type="number"
                        placeholder={derived != null ? String(derived) : "—"}
                        value={manual ? (l.unit_price ?? "") : ""}
                        disabled={isFinal}
                        onChange={(e) =>
                          patchLine(l.id, {
                            unit_price: e.target.value || null,
                            _priceEdited: true,
                          })
                        }
                      />
                    </td>
                    <td className="px-2 py-1 font-medium">
                      {total != null ? money(String(total), ccy) : "—"}
                    </td>
                    <td className="px-1 py-1">
                      {!isFinal && (
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => removeLine(l.id)}
                          aria-label="Remove line"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          {!isFinal && (
            <Button size="sm" variant="outline" onClick={addLine}>
              <Plus className="h-4 w-4" /> Add line
            </Button>
          )}
          <div className="ml-auto space-y-0.5 text-right text-sm">
            <div className="text-muted-foreground">
              Subtotal: {money(String(preview.subtotal), ccy)}
            </div>
            {gstEnabled && (
              <div className="text-muted-foreground">
                GST: {money(String(preview.tax), ccy)}
              </div>
            )}
            <div className="text-base font-semibold">
              Total: {money(String(preview.grand), ccy)}
            </div>
          </div>
        </div>

        {!isFinal && (
          <div className="flex justify-end">
            <Button onClick={() => save.mutate()} disabled={save.isPending}>
              {save.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : null}
              Save changes
            </Button>
          </div>
        )}
      </CardContent>

      {/* After saving, offer the finished quote as a download. */}
      <Dialog open={downloadPromptOpen} onOpenChange={setDownloadPromptOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Quotation saved — download it?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Choose a format for {quotation.quote_no}. You can always download
            again later from the buttons at the top.
          </p>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <Button
              variant="outline"
              className="h-auto flex-col gap-1 py-3"
              disabled={download.isPending}
              onClick={() => download.mutate("docx")}
            >
              <FileDown className="h-5 w-5" />
              <span>Word (DOCX)</span>
              <span className="text-xs font-normal text-muted-foreground">
                Customer-facing
              </span>
            </Button>
            <Button
              variant="outline"
              className="h-auto flex-col gap-1 py-3"
              disabled={download.isPending}
              onClick={() => download.mutate("xlsx")}
            >
              <FileSpreadsheet className="h-5 w-5" />
              <span>Excel (XLSX)</span>
              <span className="text-xs font-normal text-muted-foreground">
                Internal buildup
              </span>
            </Button>
          </div>
          <div className="mt-1 flex justify-end">
            <Button variant="ghost" size="sm" onClick={() => setDownloadPromptOpen(false)}>
              Not now
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
