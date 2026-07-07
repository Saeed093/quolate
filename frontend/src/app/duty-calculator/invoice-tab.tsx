"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Calculator,
  ChevronDown,
  ChevronRight,
  ClipboardType,
  FileSearch,
  Library,
  Loader2,
  Plus,
  Sparkles,
  Trash2,
  UploadCloud,
} from "lucide-react";
import {
  api,
  type HsCandidate,
  type InvoiceCalcItemResult,
  type InvoiceCalcRequest,
  type InvoiceCalcResult,
  type InvoiceCurrency,
  type InvoiceParseResult,
  type LibraryDocument,
  type RateSource,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/use-toast";
import { cn } from "@/lib/utils";
import { CandidateButtons } from "./candidates";
import { formatPkr, fractionToPct, pctToFraction } from "./format";

/** Sheet defaults, in percent-display units. */
const DEFAULT_RATES_PCT = {
  cd: "5",
  acd: "2",
  rd: "15",
  st: "18",
  ast: "3",
  ait: "5.5",
};

type RatesPct = typeof DEFAULT_RATES_PCT;

const RATE_FIELDS: { key: keyof RatesPct; label: string }[] = [
  { key: "cd", label: "Customs Duty %" },
  { key: "acd", label: "Additional CD %" },
  { key: "rd", label: "Regulatory Duty %" },
  { key: "st", label: "Sales Tax %" },
  { key: "ast", label: "Additional ST %" },
  { key: "ait", label: "Advance Income Tax %" },
];

const RATE_SOURCE_LABELS: Record<RateSource, string> = {
  memory: "remembered",
  approved_rate: "rate table",
  default: "default",
};

//: Auto-classification is sequential LLM work -- cap it; the rest get a button.
const AUTO_CLASSIFY_LIMIT = 10;

interface ItemRow {
  key: string;
  description: string;
  quantity: string;
  unit: string;
  unitPrice: string;
  lineTotal: string;
  hsCode: string;
  candidates: HsCandidate[] | null;
  classifying: boolean;
  ratesPct: RatesPct;
  fedAmount: string;
  rateSources: Record<string, RateSource> | null;
  ratesEdited: boolean;
  expanded: boolean;
}

function emptyRow(): ItemRow {
  return {
    key: crypto.randomUUID(),
    description: "",
    quantity: "",
    unit: "",
    unitPrice: "",
    lineTotal: "",
    hsCode: "",
    candidates: null,
    classifying: false,
    ratesPct: { ...DEFAULT_RATES_PCT },
    fedAmount: "0",
    rateSources: null,
    ratesEdited: false,
    expanded: false,
  };
}

export function InvoiceTab() {
  const qc = useQueryClient();

  // ---- Items ----
  const [items, setItems] = useState<ItemRow[]>([]);
  const classifyGen = useRef(0);

  const updateItem = useCallback((key: string, patch: Partial<ItemRow>) => {
    setItems((prev) =>
      prev.map((it) => (it.key === key ? { ...it, ...patch } : it)),
    );
  }, []);

  // ---- Invoice-level inputs ----
  const [currency, setCurrency] = useState<InvoiceCurrency>("USD");
  const [fxRate, setFxRate] = useState("");
  const [fxEdited, setFxEdited] = useState(false);
  const [freight, setFreight] = useState("0");
  const [insurancePct, setInsurancePct] = useState("1");
  const [landingPct, setLandingPct] = useState("1");
  const [showFees, setShowFees] = useState(false);
  const [afuPct, setAfuPct] = useState("0.8");
  const [afuFixed, setAfuFixed] = useState("3");
  const [stampFee, setStampFee] = useState("2000");
  const [pswFee, setPswFee] = useState("1000");

  const fx = useQuery({
    queryKey: ["duty-fx-rate", currency],
    queryFn: () => api.fxRate(currency),
    staleTime: 60 * 60 * 1000,
  });

  useEffect(() => {
    if (fx.data && !fxEdited) {
      setFxRate(String(Number(Number(fx.data.rate).toFixed(4))));
    }
  }, [fx.data, fxEdited]);

  // ---- Rate prefill ----
  const prefillRates = useCallback(
    async (key: string, hsCode: string, gen?: number) => {
      const code = hsCode.trim();
      if (!code) return;
      try {
        const prefill = await api.ratePrefill(code);
        if (gen !== undefined && classifyGen.current !== gen) return;
        setItems((prev) =>
          prev.map((it) => {
            if (it.key !== key || it.ratesEdited) return it;
            const pct = { ...it.ratesPct };
            for (const { key: rk } of RATE_FIELDS) {
              if (prefill.rates[rk] != null) pct[rk] = fractionToPct(prefill.rates[rk]);
            }
            return {
              ...it,
              ratesPct: pct,
              fedAmount: prefill.rates.fed_amount_pkr ?? it.fedAmount,
              rateSources: prefill.sources,
            };
          }),
        );
      } catch {
        // Prefill is best-effort; the defaults stay in place.
      }
    },
    [],
  );

  // ---- Per-item HS classification (sequential, progressive) ----
  const classifyRow = useCallback(
    async (row: ItemRow, gen: number) => {
      if (!row.description.trim()) return;
      updateItem(row.key, { classifying: true });
      try {
        const res = await api.classifyHsCode({ text: row.description });
        if (classifyGen.current !== gen) return;
        const top = res.candidates[0];
        updateItem(row.key, {
          candidates: res.candidates,
          classifying: false,
          ...(top ? { hsCode: top.hs_code } : {}),
        });
        if (top) await prefillRates(row.key, top.hs_code, gen);
      } catch {
        if (classifyGen.current !== gen) return;
        updateItem(row.key, { classifying: false, candidates: [] });
      }
    },
    [prefillRates, updateItem],
  );

  const autoClassify = useCallback(
    async (rows: ItemRow[]) => {
      const gen = ++classifyGen.current;
      for (const row of rows.slice(0, AUTO_CLASSIFY_LIMIT)) {
        if (classifyGen.current !== gen) return;
        await classifyRow(row, gen);
      }
    },
    [classifyRow],
  );

  // ---- Parse an invoice document / pasted text ----
  const [selectedLibraryDocId, setSelectedLibraryDocId] = useState("");
  const [pastedText, setPastedText] = useState("");
  const [parseInfo, setParseInfo] = useState<InvoiceParseResult | null>(null);

  const libraryDocs = useQuery({
    queryKey: ["library-documents"],
    queryFn: api.listLibraryDocuments,
  });

  function seedFromParse(data: InvoiceParseResult) {
    setParseInfo(data);
    if (data.items.length === 0) {
      toast({
        title: "No line items found",
        description: "Add items manually below, or try a clearer document.",
      });
      return;
    }
    const rows = data.items.map((p) => ({
      ...emptyRow(),
      description: p.description,
      quantity: p.quantity ?? "",
      unit: p.unit ?? "",
      unitPrice: p.unit_price ?? "",
      lineTotal: p.line_total ?? "",
    }));
    setItems(rows);
    if (data.invoice_currency === "USD" || data.invoice_currency === "CNY") {
      setCurrency(data.invoice_currency);
      setFxEdited(false);
    }
    if (Number(data.freight) > 0) setFreight(data.freight);
    calc.reset();
    void autoClassify(rows);
  }

  const onParseError = (err: unknown) =>
    toast({
      title: "Could not read the invoice",
      description: err instanceof Error ? err.message : undefined,
      variant: "destructive",
    });

  const parseDoc = useMutation({
    mutationFn: (libraryDocumentId: string) =>
      api.parseInvoice({ library_document_id: libraryDocumentId }),
    onSuccess: seedFromParse,
    onError: onParseError,
  });

  const uploadAndParse = useMutation({
    mutationFn: async (files: File[]) => {
      const uploaded = await api.uploadLibraryDocuments(files);
      const docId = uploaded.created[0]?.id ?? uploaded.skipped[0]?.id;
      if (!docId) {
        throw new Error(
          uploaded.errors[0]?.error ?? "Upload did not produce a usable document",
        );
      }
      qc.invalidateQueries({ queryKey: ["library-documents"] });
      return api.parseInvoice({ library_document_id: docId });
    },
    onSuccess: seedFromParse,
    onError: onParseError,
  });

  const parseText = useMutation({
    mutationFn: (text: string) => api.parseInvoice({ text }),
    onSuccess: seedFromParse,
    onError: onParseError,
  });

  const onDrop = useCallback(
    (accepted: File[]) => {
      if (accepted.length) uploadAndParse.mutate(accepted);
    },
    [uploadAndParse],
  );
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: false,
  });

  const parsing =
    parseDoc.isPending || uploadAndParse.isPending || parseText.isPending;

  // ---- Calculate ----
  const calc = useMutation({
    mutationFn: () => {
      if (items.length === 0) throw new Error("Add at least one item");
      const rate = Number(fxRate);
      if (!Number.isFinite(rate) || rate <= 0)
        throw new Error("Conversion rate must be greater than 0");
      const body: InvoiceCalcRequest = {
        currency,
        fx_rate: fxRate,
        fx_rate_date: fx.data && !fxEdited ? fx.data.as_of_date : null,
        freight: freight || "0",
        insurance_pct: pctToFraction(insurancePct),
        landing_pct: pctToFraction(landingPct),
        fees: {
          afu_pct: pctToFraction(afuPct),
          afu_fixed_pkr: afuFixed || "0",
          stamp_fee_pkr: stampFee || "0",
          psw_fee_pkr: pswFee || "0",
        },
        save_rates: true,
        items: items.map((it, i) => {
          if (!it.hsCode.trim())
            throw new Error(`Item ${i + 1}: pick or enter an HS code`);
          const hasTotal = it.lineTotal !== "" && Number(it.lineTotal) >= 0;
          const hasQtyPrice = it.quantity !== "" && it.unitPrice !== "";
          if (!hasTotal && !hasQtyPrice)
            throw new Error(
              `Item ${i + 1}: enter a line total, or quantity and unit price`,
            );
          return {
            description: it.description,
            quantity: it.quantity || null,
            unit: it.unit || null,
            unit_price: it.unitPrice || null,
            line_total: it.lineTotal || null,
            hs_code: it.hsCode.trim(),
            fed_amount_pkr: it.fedAmount || "0",
            rates: {
              cd: pctToFraction(it.ratesPct.cd),
              acd: pctToFraction(it.ratesPct.acd),
              rd: pctToFraction(it.ratesPct.rd),
              st: pctToFraction(it.ratesPct.st),
              ast: pctToFraction(it.ratesPct.ast),
              ait: pctToFraction(it.ratesPct.ait),
            },
          };
        }),
      };
      return api.invoiceDutyCalc(body);
    },
    onError: (err) =>
      toast({
        title: "Could not calculate",
        description: err instanceof Error ? err.message : undefined,
        variant: "destructive",
      }),
  });

  const result = calc.data;

  return (
    <div className="flex flex-col gap-6">
      {/* ---- Source ---- */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="h-4 w-4 text-primary" />
            Read an invoice or quotation
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            Line items are extracted automatically, then each one gets HS code
            suggestions you can pick from. Everything stays editable.
          </p>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="upload">
            <TabsList>
              <TabsTrigger value="upload" className="gap-1.5">
                <UploadCloud className="h-3.5 w-3.5" />
                Upload
              </TabsTrigger>
              <TabsTrigger value="library" className="gap-1.5">
                <Library className="h-3.5 w-3.5" />
                From library
              </TabsTrigger>
              <TabsTrigger value="paste" className="gap-1.5">
                <ClipboardType className="h-3.5 w-3.5" />
                Paste text
              </TabsTrigger>
            </TabsList>

            <TabsContent value="upload">
              <div
                {...getRootProps()}
                className={cn(
                  "flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed border-border/70 px-4 py-8 text-center transition-colors",
                  isDragActive && "border-primary bg-primary/5",
                  uploadAndParse.isPending && "pointer-events-none opacity-60",
                )}
              >
                <input {...getInputProps()} />
                {uploadAndParse.isPending ? (
                  <Loader2 className="h-6 w-6 animate-spin text-primary" />
                ) : (
                  <UploadCloud className="h-6 w-6 text-muted-foreground" />
                )}
                <p className="text-sm font-medium">
                  {uploadAndParse.isPending
                    ? "Uploading and reading line items…"
                    : "Drag an invoice here, or click to browse"}
                </p>
                <p className="text-[11px] text-muted-foreground">
                  PDF, image, Word, Excel or text — saved to your document
                  library either way.
                </p>
              </div>
            </TabsContent>

            <TabsContent value="library">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:gap-3">
                <div className="flex-1">
                  <select
                    className="select-base"
                    value={selectedLibraryDocId}
                    onChange={(e) => setSelectedLibraryDocId(e.target.value)}
                  >
                    <option value="">
                      {libraryDocs.isLoading
                        ? "Loading documents…"
                        : (libraryDocs.data?.length ?? 0) === 0
                          ? "No documents in your library yet"
                          : "Select a document…"}
                    </option>
                    {libraryDocs.data?.map((d: LibraryDocument) => (
                      <option key={d.id} value={d.id}>
                        {d.filename}
                      </option>
                    ))}
                  </select>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  disabled={!selectedLibraryDocId || parseDoc.isPending}
                  onClick={() => parseDoc.mutate(selectedLibraryDocId)}
                  className="gap-2"
                >
                  {parseDoc.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <FileSearch className="h-4 w-4" />
                  )}
                  Read items
                </Button>
              </div>
            </TabsContent>

            <TabsContent value="paste">
              <div className="flex flex-col gap-2">
                <Textarea
                  rows={6}
                  placeholder="Paste the invoice or quotation text here…"
                  value={pastedText}
                  onChange={(e) => setPastedText(e.target.value)}
                />
                <div>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={!pastedText.trim() || parseText.isPending}
                    onClick={() => parseText.mutate(pastedText)}
                    className="gap-2"
                  >
                    {parseText.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <FileSearch className="h-4 w-4" />
                    )}
                    Read items
                  </Button>
                </div>
              </div>
            </TabsContent>
          </Tabs>

          {parsing && (
            <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Extracting line items — this can take a little while on CPU.
            </p>
          )}
          {parseInfo && !parsing && (
            <p className="mt-4 text-[11px] text-muted-foreground">
              {parseInfo.disclaimer}
            </p>
          )}
        </CardContent>
      </Card>

      {/* ---- Items ---- */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">
            Items{items.length > 0 ? ` (${items.length})` : ""}
          </CardTitle>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => setItems((prev) => [...prev, emptyRow()])}
          >
            <Plus className="h-3.5 w-3.5" />
            Add item
          </Button>
        </CardHeader>
        <CardContent>
          {items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Read an invoice above, or add items manually.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8" />
                    <TableHead className="min-w-[200px]">Description</TableHead>
                    <TableHead className="w-24 min-w-[5.5rem]">Qty</TableHead>
                    <TableHead className="w-32 min-w-[7rem]">
                      Unit price ({currency})
                    </TableHead>
                    <TableHead className="w-32 min-w-[7rem]">
                      Line total ({currency})
                    </TableHead>
                    <TableHead className="min-w-[260px]">HS / PCT code</TableHead>
                    <TableHead className="w-8" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((it, index) => (
                    <ItemRows
                      key={it.key}
                      item={it}
                      index={index}
                      onChange={(patch) => updateItem(it.key, patch)}
                      onPickCandidate={(c) => {
                        updateItem(it.key, { hsCode: c.hs_code });
                        void prefillRates(it.key, c.hs_code);
                      }}
                      onHsBlur={() => void prefillRates(it.key, it.hsCode)}
                      onSuggest={() =>
                        void classifyRow(it, ++classifyGen.current)
                      }
                      onRemove={() =>
                        setItems((prev) => prev.filter((r) => r.key !== it.key))
                      }
                    />
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ---- Invoice-level inputs ---- */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Invoice details</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="inv-currency">Invoice currency</Label>
              <select
                id="inv-currency"
                className="select-base"
                value={currency}
                onChange={(e) => {
                  setCurrency(e.target.value as InvoiceCurrency);
                  setFxEdited(false);
                }}
              >
                <option value="USD">USD — US Dollar</option>
                <option value="CNY">CNY — Chinese Yuan</option>
              </select>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="inv-fx">Conversion rate (PKR per {currency})</Label>
              <Input
                id="inv-fx"
                type="number"
                inputMode="decimal"
                min={0}
                step="0.0001"
                value={fxRate}
                onChange={(e) => {
                  setFxRate(e.target.value);
                  setFxEdited(true);
                }}
              />
              <p className="text-[11px] text-muted-foreground">
                {fxEdited ? (
                  "Manual rate."
                ) : fx.isLoading ? (
                  "Fetching today's rate…"
                ) : fx.data ? (
                  <>
                    <Badge
                      variant={fx.data.source === "live" ? "ok" : "verify"}
                      className="mr-1 text-[10px]"
                    >
                      {fx.data.source === "live"
                        ? `live · ${fx.data.as_of_date}`
                        : "offline table — verify"}
                    </Badge>
                    Open-market rate; customs uses the FBR-notified rate, so
                    adjust if needed.
                  </>
                ) : (
                  "Enter the customs-notified rate."
                )}
              </p>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="inv-freight">Freight ({currency})</Label>
              <Input
                id="inv-freight"
                type="number"
                inputMode="decimal"
                min={0}
                step="0.01"
                value={freight}
                onChange={(e) => setFreight(e.target.value)}
              />
              <p className="text-[11px] text-muted-foreground">
                Allocated across items pro-rata by line value.
              </p>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="inv-insurance">Insurance %</Label>
              <Input
                id="inv-insurance"
                type="number"
                inputMode="decimal"
                min={0}
                step="0.01"
                value={insurancePct}
                onChange={(e) => setInsurancePct(e.target.value)}
              />
              <p className="text-[11px] text-muted-foreground">
                Of C&amp;F value — 1% or as per memo.
              </p>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="inv-landing">Landing charges %</Label>
              <Input
                id="inv-landing"
                type="number"
                inputMode="decimal"
                min={0}
                step="0.01"
                value={landingPct}
                onChange={(e) => setLandingPct(e.target.value)}
              />
              <p className="text-[11px] text-muted-foreground">
                Of C&amp;F + insurance.
              </p>
            </div>
          </div>

          <button
            type="button"
            className="mt-4 flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
            onClick={() => setShowFees((v) => !v)}
          >
            {showFees ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
            Fixed fees (Excise AFU, Stamps, PSW GD fee)
          </button>
          {showFees && (
            <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="fee-afu-pct">Excise &amp; Taxation AFU %</Label>
                <Input
                  id="fee-afu-pct"
                  type="number"
                  inputMode="decimal"
                  min={0}
                  step="0.01"
                  value={afuPct}
                  onChange={(e) => setAfuPct(e.target.value)}
                />
                <p className="text-[11px] text-muted-foreground">
                  Of total import value.
                </p>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="fee-afu-fixed">AFU fixed (PKR)</Label>
                <Input
                  id="fee-afu-fixed"
                  type="number"
                  inputMode="decimal"
                  min={0}
                  step="1"
                  value={afuFixed}
                  onChange={(e) => setAfuFixed(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="fee-stamp">Stamps (PKR)</Label>
                <Input
                  id="fee-stamp"
                  type="number"
                  inputMode="decimal"
                  min={0}
                  step="1"
                  value={stampFee}
                  onChange={(e) => setStampFee(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="fee-psw">PSW GD fee (PKR)</Label>
                <Input
                  id="fee-psw"
                  type="number"
                  inputMode="decimal"
                  min={0}
                  step="1"
                  value={pswFee}
                  onChange={(e) => setPswFee(e.target.value)}
                />
              </div>
            </div>
          )}

          <div className="mt-5">
            <Button
              type="button"
              disabled={calc.isPending || items.length === 0}
              onClick={() => calc.mutate()}
              className="gap-2"
            >
              {calc.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Calculator className="h-4 w-4" />
              )}
              Calculate duties &amp; landed price
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* ---- Results ---- */}
      {result && <InvoiceResults result={result} />}
    </div>
  );
}

/** One item = the main row plus an optional expanded rate-editor row. */
function ItemRows({
  item,
  index,
  onChange,
  onPickCandidate,
  onHsBlur,
  onSuggest,
  onRemove,
}: {
  item: ItemRow;
  index: number;
  onChange: (patch: Partial<ItemRow>) => void;
  onPickCandidate: (c: HsCandidate) => void;
  onHsBlur: () => void;
  onSuggest: () => void;
  onRemove: () => void;
}) {
  const editRates = (key: keyof RatesPct, value: string) =>
    onChange({
      ratesPct: { ...item.ratesPct, [key]: value },
      ratesEdited: true,
      rateSources: null,
    });

  return (
    <>
      <TableRow>
        <TableCell className="align-top">
          <button
            type="button"
            className="mt-2 text-muted-foreground hover:text-foreground"
            onClick={() => onChange({ expanded: !item.expanded })}
            title="Edit duty rates for this item"
          >
            {item.expanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>
        </TableCell>
        <TableCell className="align-top">
          <Input
            value={item.description}
            placeholder={`Item ${index + 1} description`}
            onChange={(e) => onChange({ description: e.target.value })}
          />
        </TableCell>
        <TableCell className="align-top">
          <Input
            type="number"
            inputMode="decimal"
            min={0}
            value={item.quantity}
            onChange={(e) => onChange({ quantity: e.target.value })}
          />
        </TableCell>
        <TableCell className="align-top">
          <Input
            type="number"
            inputMode="decimal"
            min={0}
            step="0.01"
            value={item.unitPrice}
            onChange={(e) => onChange({ unitPrice: e.target.value })}
          />
        </TableCell>
        <TableCell className="align-top">
          <Input
            type="number"
            inputMode="decimal"
            min={0}
            step="0.01"
            placeholder="qty × price"
            value={item.lineTotal}
            onChange={(e) => onChange({ lineTotal: e.target.value })}
          />
        </TableCell>
        <TableCell className="align-top">
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2">
              <Input
                className="font-mono"
                placeholder="e.g. 8517.12.00"
                value={item.hsCode}
                onChange={(e) => onChange({ hsCode: e.target.value })}
                onBlur={onHsBlur}
              />
              {item.classifying ? (
                <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />
              ) : (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="shrink-0 gap-1 px-2 text-xs"
                  onClick={onSuggest}
                  disabled={!item.description.trim()}
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  Suggest
                </Button>
              )}
            </div>
            {item.candidates && item.candidates.length > 0 && (
              <CandidateButtons
                compact
                candidates={item.candidates}
                selectedHsCode={item.hsCode}
                onPick={onPickCandidate}
              />
            )}
            {item.candidates && item.candidates.length === 0 && (
              <p className="text-[11px] text-muted-foreground">
                No suggestion — enter the HS code manually.
              </p>
            )}
          </div>
        </TableCell>
        <TableCell className="align-top">
          <button
            type="button"
            className="mt-2 text-muted-foreground hover:text-destructive"
            onClick={onRemove}
            title="Remove item"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </TableCell>
      </TableRow>

      {item.expanded && (
        <TableRow className="bg-muted/30 hover:bg-muted/30">
          <TableCell />
          <TableCell colSpan={6}>
            <div className="grid grid-cols-2 gap-3 py-1 sm:grid-cols-4 lg:grid-cols-7">
              {RATE_FIELDS.map(({ key, label }) => (
                <div key={key} className="flex flex-col gap-1">
                  <Label className="text-[11px]">{label}</Label>
                  <Input
                    type="number"
                    inputMode="decimal"
                    min={0}
                    step="0.01"
                    value={item.ratesPct[key]}
                    onChange={(e) => editRates(key, e.target.value)}
                  />
                  <span className="text-[10px] text-muted-foreground">
                    {item.ratesEdited
                      ? "edited"
                      : RATE_SOURCE_LABELS[item.rateSources?.[key] ?? "default"]}
                  </span>
                </div>
              ))}
              <div className="flex flex-col gap-1">
                <Label className="text-[11px]">FED / fine (PKR)</Label>
                <Input
                  type="number"
                  inputMode="decimal"
                  min={0}
                  step="0.01"
                  value={item.fedAmount}
                  onChange={(e) =>
                    onChange({ fedAmount: e.target.value, ratesEdited: true })
                  }
                />
                <span className="text-[10px] text-muted-foreground">
                  manual amount
                </span>
              </div>
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

function InvoiceResults({ result }: { result: InvoiceCalcResult }) {
  const t = result.totals;
  return (
    <div className="flex animate-fade-in-up flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Invoice summary</CardTitle>
          <p className="text-xs text-muted-foreground">
            {Number(t.invoice_value).toLocaleString()} {result.currency} goods
            {Number(t.freight) > 0 &&
              ` + ${Number(t.freight).toLocaleString()} ${result.currency} freight`}{" "}
            × {result.fx_rate} PKR/{result.currency}
            {result.fx_rate_date ? ` (rate of ${result.fx_rate_date})` : ""}
          </p>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-1.5 text-sm">
            <SummaryRow label="Goods value C&F (PKR)" value={t.cf_value_pkr} />
            <SummaryRow
              label="Import value (incl. insurance + landing)"
              value={t.import_value_pkr}
            />
            <SummaryRow
              label="Duties & taxes (Collector of Customs)"
              value={t.customs_total_pkr}
            />
            <SummaryRow label="Excise & Taxation AFU" value={t.afu_pkr} />
            <SummaryRow label="Stamps" value={t.stamp_fee_pkr} />
            <SummaryRow label="PSW GD fee" value={t.psw_fee_pkr} />
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-end gap-6 border-t border-border/60 pt-4">
            <div className="text-right">
              <p className="text-xs text-muted-foreground">
                Total taxes, duties &amp; fees
              </p>
              <p className="text-lg font-semibold">
                {formatPkr(t.total_payable_pkr)}
              </p>
            </div>
            <div className="text-right">
              <p className="text-xs text-muted-foreground">
                Total landed cleared price
              </p>
              <p className="text-xl font-bold text-primary">
                {formatPkr(t.landed_cleared_price_pkr)}
              </p>
            </div>
          </div>
          <p className="mt-3 text-[11px] text-muted-foreground">
            Insurance and landing charges are customs valuation add-ons (they
            raise the duty base), not cash costs — the landed price is goods
            C&amp;F plus everything payable.
          </p>
          <p className="mt-3 rounded-lg border border-verify/30 bg-verify/10 px-3 py-2 text-[11px] text-muted-foreground">
            {result.disclaimer}
          </p>
        </CardContent>
      </Card>

      {result.items.map((item, i) => (
        <ItemResultCard key={i} item={item} index={i} currency={result.currency} />
      ))}
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="tabular-nums">{formatPkr(value)}</span>
    </div>
  );
}

function ItemResultCard({
  item,
  index,
  currency,
}: {
  item: InvoiceCalcItemResult;
  index: number;
  currency: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">
          {index + 1}. {item.description || "Item"}{" "}
          <span className="ml-1 font-mono text-xs font-normal text-muted-foreground">
            {item.hs_code}
          </span>
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          {Number(item.line_total).toLocaleString()} {currency}
          {Number(item.freight_allocated) > 0 &&
            ` + ${Number(item.freight_allocated).toLocaleString()} ${currency} freight share`}{" "}
          → C&amp;F {formatPkr(item.cf_value_pkr)} · + insurance{" "}
          {formatPkr(item.insurance_pkr)} + landing {formatPkr(item.landing_pkr)} →
          import value <span className="font-medium text-foreground">{formatPkr(item.import_value_pkr)}</span>
        </p>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Levy</TableHead>
              <TableHead>Rate</TableHead>
              <TableHead className="text-right">Base</TableHead>
              <TableHead className="text-right">Amount</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {item.levies.map((line) => (
              <TableRow key={line.levy_type}>
                <TableCell className="font-medium">{line.label}</TableCell>
                <TableCell>
                  {line.levy_type === "FED"
                    ? "manual"
                    : `${(Number(line.rate) * 100).toFixed(2)}%`}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {line.levy_type === "FED" ? "—" : formatPkr(line.basis_pkr)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatPkr(line.amount_pkr)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <div className="mt-3 flex flex-wrap items-center justify-end gap-6 border-t border-border/60 pt-3 text-sm">
          <div className="text-right">
            <p className="text-xs text-muted-foreground">Duties &amp; taxes (item)</p>
            <p className="font-semibold">{formatPkr(item.item_duty_total_pkr)}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
