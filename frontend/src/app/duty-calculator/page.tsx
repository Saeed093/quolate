"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useDropzone } from "react-dropzone";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Calculator,
  FileSearch,
  Library,
  Loader2,
  Search,
  Sparkles,
  UploadCloud,
} from "lucide-react";
import {
  api,
  getToken,
  IMPORTER_CATEGORIES,
  type AtlStatus,
  type DutyCalculation,
  type HsCandidate,
  type HsClassificationResult,
  type LibraryDocument,
} from "@/lib/api";
import { AppNav } from "@/components/AppNav";
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
import { toast } from "@/components/ui/use-toast";
import { cn } from "@/lib/utils";
import { CandidateButtons } from "./candidates";
import { formatPkr, formatRate } from "./format";
import { InvoiceTab } from "./invoice-tab";

export default function DutyCalculatorPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const formRef = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<"single" | "invoice">("single");

  // ---- Form state ----
  const [hsCode, setHsCode] = useState("");
  const [hsFocused, setHsFocused] = useState(false);
  const [declaredValue, setDeclaredValue] = useState("");
  const [exchangeRate, setExchangeRate] = useState("");
  const [importerCategory, setImporterCategory] = useState("");
  const [atlStatus, setAtlStatus] = useState<AtlStatus | "">("");
  const [asOfDate, setAsOfDate] = useState("");

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [hsSearch, setHsSearch] = useState("");
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setHsSearch(hsCode.trim()), 250);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [hsCode]);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const suggestions = useQuery({
    queryKey: ["duty-hs-codes", hsSearch],
    queryFn: () => api.dutyHsCodes(hsSearch || undefined),
    enabled: hsFocused,
  });

  const calc = useMutation({
    mutationFn: () => {
      const value = Number(declaredValue);
      const rate = Number(exchangeRate);
      if (!hsCode.trim()) throw new Error("Enter an HS code");
      if (!Number.isFinite(value) || value <= 0)
        throw new Error("Declared value must be greater than 0");
      if (!Number.isFinite(rate) || rate <= 0)
        throw new Error("Exchange rate must be greater than 0");
      return api.dutyCalc(hsCode.trim(), {
        declared_value_usd: value,
        exchange_rate: rate,
        importer_category: importerCategory || undefined,
        atl_status: atlStatus || undefined,
        as_of_date: asOfDate || undefined,
      });
    },
    onError: (err) =>
      toast({
        title: "Could not calculate",
        description: err instanceof Error ? err.message : undefined,
        variant: "destructive",
      }),
  });

  const result = calc.data;

  // ---- Auto-detect HS code from a document ----
  const [selectedLibraryDocId, setSelectedLibraryDocId] = useState("");
  const [classification, setClassification] = useState<HsClassificationResult | null>(
    null,
  );

  const libraryDocs = useQuery({
    queryKey: ["library-documents"],
    queryFn: api.listLibraryDocuments,
  });

  const classifyDoc = useMutation({
    mutationFn: (libraryDocumentId: string) =>
      api.classifyHsCode({ library_document_id: libraryDocumentId }),
    onSuccess: (data) => setClassification(data),
    onError: (err) =>
      toast({
        title: "Could not classify document",
        description: err instanceof Error ? err.message : undefined,
        variant: "destructive",
      }),
  });

  const uploadAndClassify = useMutation({
    mutationFn: async (files: File[]) => {
      const uploaded = await api.uploadLibraryDocuments(files);
      const docId = uploaded.created[0]?.id ?? uploaded.skipped[0]?.id;
      if (!docId) {
        throw new Error(
          uploaded.errors[0]?.error ?? "Upload did not produce a usable document",
        );
      }
      qc.invalidateQueries({ queryKey: ["library-documents"] });
      return api.classifyHsCode({ library_document_id: docId });
    },
    onSuccess: (data) => setClassification(data),
    onError: (err) =>
      toast({
        title: "Could not classify document",
        description: err instanceof Error ? err.message : undefined,
        variant: "destructive",
      }),
  });

  const onDropDetect = useCallback(
    (accepted: File[]) => {
      if (accepted.length) uploadAndClassify.mutate(accepted);
    },
    [uploadAndClassify],
  );
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: onDropDetect,
    multiple: false,
  });

  const classifying = classifyDoc.isPending || uploadAndClassify.isPending;

  function applyCandidate(candidate: HsCandidate) {
    setHsCode(candidate.hs_code);
    toast({ title: `HS code set to ${candidate.hs_code}`, description: "Review and calculate below." });
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // Running subtotal starting from the assessed value, added to as each levy compounds.
  const runningRows = useMemo(() => {
    if (!result) return [];
    let running = Number(result.assessed_value_pkr);
    return result.levies.map((line) => {
      running += Number(line.amount_pkr);
      return { line, running };
    });
  }, [result]);

  return (
    <div className="min-h-screen">
      <AppNav />
      <main
        className={cn(
          "mx-auto px-4 py-6 sm:px-6",
          mode === "invoice" ? "max-w-6xl" : "max-w-4xl",
        )}
      >
        <div className="mb-1 flex items-center gap-2">
          <Calculator className="h-5 w-5 text-primary" />
          <h1 className="text-2xl font-semibold tracking-tight">
            Pakistan Duty &amp; Tax Calculator
          </h1>
        </div>
        <p className="mb-4 text-sm text-muted-foreground">
          Full landed-cost breakdown: Customs Duty, Additional Customs Duty,
          Regulatory Duty, Sales Tax, Additional Sales Tax, FED, and advance
          Income Tax — for a single HS code or a whole invoice, item by item.
        </p>

        <div className="mb-6 flex items-start gap-2 rounded-xl border border-verify/30 bg-verify/10 px-3.5 py-3 text-xs text-foreground">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-verify" />
          <p>
            This is a calculation aid based on ingested rate data, not a
            substitute for the actual statute/SRO text or a customs agent&apos;s
            WeBOC-assessed figure. Verify before relying on this for a
            client-facing quote or a filing.
          </p>
        </div>

        <Tabs
          value={mode}
          onValueChange={(v) => setMode(v as "single" | "invoice")}
        >
          <TabsList className="mb-4">
            <TabsTrigger value="single">Single item</TabsTrigger>
            <TabsTrigger value="invoice">Invoice / multi-item</TabsTrigger>
          </TabsList>

          <TabsContent value="invoice">
            <InvoiceTab />
          </TabsContent>

          <TabsContent value="single">
        <Card className="mb-6">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Sparkles className="h-4 w-4 text-primary" />
              Auto-detect from a document
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              Upload an invoice, packing list or spec sheet — or pick one you
              already saved — and let the assistant suggest an HS code.
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
              </TabsList>

              <TabsContent value="upload">
                <div
                  {...getRootProps()}
                  className={cn(
                    "flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed border-border/70 px-4 py-8 text-center transition-colors",
                    isDragActive && "border-primary bg-primary/5",
                    uploadAndClassify.isPending && "pointer-events-none opacity-60",
                  )}
                >
                  <input {...getInputProps()} />
                  {uploadAndClassify.isPending ? (
                    <Loader2 className="h-6 w-6 animate-spin text-primary" />
                  ) : (
                    <UploadCloud className="h-6 w-6 text-muted-foreground" />
                  )}
                  <p className="text-sm font-medium">
                    {uploadAndClassify.isPending
                      ? "Uploading and classifying…"
                      : "Drag a file here, or click to browse"}
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
                    disabled={!selectedLibraryDocId || classifyDoc.isPending}
                    onClick={() => classifyDoc.mutate(selectedLibraryDocId)}
                    className="gap-2"
                  >
                    {classifyDoc.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <FileSearch className="h-4 w-4" />
                    )}
                    Classify
                  </Button>
                </div>
              </TabsContent>
            </Tabs>

            {classifying && !classification && (
              <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Asking the assistant to suggest an HS code — this can take a
                little while on CPU.
              </p>
            )}

            {classification && (
              <div className="mt-4 flex flex-col gap-2">
                {classification.product_summary && (
                  <p className="text-xs text-muted-foreground">
                    Detected product: <span className="font-medium text-foreground">{classification.product_summary}</span>
                  </p>
                )}
                {classification.candidates.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No candidates suggested — try a clearer document or enter
                    the HS code manually.
                  </p>
                ) : (
                  <CandidateButtons
                    candidates={classification.candidates}
                    onPick={applyCandidate}
                  />
                )}
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {classification.disclaimer}
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="mb-6" ref={formRef}>
          <CardHeader>
            <CardTitle className="text-base">Line item</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              className="grid grid-cols-1 gap-4 sm:grid-cols-2"
              onSubmit={(e) => {
                e.preventDefault();
                calc.mutate();
              }}
            >
              <div className="relative flex flex-col gap-1.5">
                <Label htmlFor="hs-code">HS / PCT code</Label>
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="hs-code"
                    className="pl-8"
                    placeholder="e.g. 8517.12.00"
                    value={hsCode}
                    onChange={(e) => setHsCode(e.target.value)}
                    onFocus={() => setHsFocused(true)}
                    onBlur={() => setTimeout(() => setHsFocused(false), 150)}
                    autoComplete="off"
                    required
                  />
                </div>
                {hsFocused && (suggestions.data?.length ?? 0) > 0 && (
                  <div className="absolute top-full z-20 mt-1 w-full overflow-hidden rounded-lg border border-border bg-popover shadow-md">
                    {suggestions.data!.map((code) => (
                      <button
                        key={code}
                        type="button"
                        className="block w-full px-3 py-1.5 text-left text-sm hover:bg-accent"
                        onClick={() => {
                          setHsCode(code);
                          setHsFocused(false);
                        }}
                      >
                        {code}
                      </button>
                    ))}
                  </div>
                )}
                {hsFocused && suggestions.data?.length === 0 && (
                  <p className="text-[11px] text-muted-foreground">
                    No ingested rates match yet — you can still enter a code
                    manually.
                  </p>
                )}
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="declared-value">Declared value (USD)</Label>
                <Input
                  id="declared-value"
                  type="number"
                  inputMode="decimal"
                  min={0}
                  step="0.01"
                  placeholder="1000"
                  value={declaredValue}
                  onChange={(e) => setDeclaredValue(e.target.value)}
                  required
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="exchange-rate">
                  Customs-notified exchange rate (PKR per USD)
                </Label>
                <Input
                  id="exchange-rate"
                  type="number"
                  inputMode="decimal"
                  min={0}
                  step="0.01"
                  placeholder="280"
                  value={exchangeRate}
                  onChange={(e) => setExchangeRate(e.target.value)}
                  required
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="as-of-date">As of date</Label>
                <Input
                  id="as-of-date"
                  type="date"
                  value={asOfDate}
                  onChange={(e) => setAsOfDate(e.target.value)}
                />
                <p className="text-[11px] text-muted-foreground">
                  Defaults to today. Change this to reproduce a past
                  calculation under the rates in force at that time.
                </p>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="importer-category">Importer category</Label>
                <select
                  id="importer-category"
                  className="select-base"
                  value={importerCategory}
                  onChange={(e) => setImporterCategory(e.target.value)}
                >
                  <option value="">General / not specified</option>
                  {IMPORTER_CATEGORIES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
                <p className="text-[11px] text-muted-foreground">
                  Some exemptions (e.g. Section 148 for industrial
                  undertakings, own use) only apply if this is declared.
                </p>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="atl-status">Active Taxpayer List status</Label>
                <select
                  id="atl-status"
                  className="select-base"
                  value={atlStatus}
                  onChange={(e) => setAtlStatus(e.target.value as AtlStatus | "")}
                >
                  <option value="">Not specified</option>
                  <option value="atl">On the ATL</option>
                  <option value="non_atl">Not on the ATL (~2x WHT)</option>
                </select>
              </div>

              <div className="sm:col-span-2">
                <Button type="submit" disabled={calc.isPending} className="gap-2">
                  {calc.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Calculator className="h-4 w-4" />
                  )}
                  Calculate
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        {result && <ResultCard result={result} runningRows={runningRows} />}
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}

function ResultCard({
  result,
  runningRows,
}: {
  result: DutyCalculation;
  runningRows: { line: DutyCalculation["levies"][number]; running: number }[];
}) {
  return (
    <Card className="animate-fade-in-up">
      <CardHeader>
        <CardTitle className="text-base">
          Breakdown for {result.hs_code}
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          As of {result.as_of_date} · Assessed value{" "}
          {formatPkr(result.assessed_value_pkr)} (
          {Number(result.declared_value_usd).toLocaleString()} USD ×{" "}
          {result.exchange_rate} PKR/USD)
        </p>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Levy</TableHead>
              <TableHead>Rate</TableHead>
              <TableHead>Reference</TableHead>
              <TableHead className="text-right">Amount</TableHead>
              <TableHead className="text-right">Running total</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {runningRows.map(({ line, running }) => (
              <TableRow key={line.levy_type}>
                <TableCell>
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium">{line.label}</span>
                    {line.exemption_applied && (
                      <Badge variant="ok" className="text-[10px]">
                        exemption applied
                      </Badge>
                    )}
                  </div>
                  {line.notes && (
                    <p className="mt-0.5 max-w-sm text-[11px] text-muted-foreground">
                      {line.notes}
                    </p>
                  )}
                </TableCell>
                <TableCell>{formatRate(line.rate, line.rate_type)}</TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {line.legal_reference && <div>{line.legal_reference}</div>}
                  {line.sro_reference && <div>{line.sro_reference}</div>}
                  {!line.legal_reference && !line.sro_reference && "—"}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatPkr(line.amount_pkr)}
                </TableCell>
                <TableCell className="text-right tabular-nums font-medium">
                  {formatPkr(running)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        <div className="mt-4 flex flex-wrap items-center justify-end gap-6 border-t border-border/60 pt-4">
          <div className="text-right">
            <p className="text-xs text-muted-foreground">Total duty &amp; tax</p>
            <p className="text-lg font-semibold">
              {formatPkr(result.total_duty_tax_pkr)}
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs text-muted-foreground">Total landed cost</p>
            <p className="text-xl font-bold text-primary">
              {formatPkr(result.total_landed_pkr)}
            </p>
          </div>
        </div>

        <p
          className={cn(
            "mt-4 rounded-lg border border-verify/30 bg-verify/10 px-3 py-2 text-[11px] text-muted-foreground",
          )}
        >
          {result.disclaimer}
        </p>
      </CardContent>
    </Card>
  );
}
