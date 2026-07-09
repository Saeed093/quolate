"use client";

import { useQuery } from "@tanstack/react-query";
import { Download, Star } from "lucide-react";
import { api, getToken, type MatrixCell, type MatrixParams } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cellStateClass, cellStateLabel } from "@/lib/matrix";
import { formatCurrency, formatNumber, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";

// Canonical display order for standard fields
const STANDARD_FIELD_ORDER = [
  "moq",
  "lead_time_days",
  "incoterms",
  "payment_terms",
  "validity_days",
  "valid_until",
  "warranty",
] as const;

type StandardField = (typeof STANDARD_FIELD_ORDER)[number];

function getFieldLabel(field: string): string {
  const labels: Record<string, string> = {
    moq: "MOQ",
    lead_time_days: "Lead time",
    incoterms: "Incoterms",
    valid_until: "Valid until",
    payment_terms: "Payment",
    warranty: "Warranty",
    validity_days: "Valid for",
  };
  if (field in labels) return labels[field];
  if (field.startsWith("spec:")) return field.slice(5);
  return field;
}

function getFieldValue(cell: MatrixCell, field: string): string {
  switch (field) {
    case "moq":
      return formatNumber(cell.moq);
    case "lead_time_days":
      return cell.lead_time_days != null ? `${cell.lead_time_days} days` : "—";
    case "incoterms":
      return cell.incoterms ?? "—";
    case "valid_until":
      return cell.valid_until ?? "—";
    case "payment_terms":
      return cell.payment_terms ?? "—";
    case "warranty":
      return cell.warranty ?? "—";
    case "validity_days":
      return cell.validity_days ?? "—";
    default:
      if (field.startsWith("spec:")) return cell.extra_fields?.[field] ?? "—";
      return "—";
  }
}

// These core fields are always shown when at least one supplier has any quote,
// so the user can see what data is present vs. missing at a glance.
const ALWAYS_SHOW_FIELDS = new Set(["moq", "lead_time_days", "incoterms"]);

/**
 * Determine which fields to show for a BOM row.
 *
 * Core fields (MOQ, lead time, incoterms) are always shown when the row has
 * at least one non-gap cell, making it easy to spot missing data.
 *
 * Optional fields (payment terms, warranty, validity, spec:*) only appear
 * when at least one supplier actually provides them.
 */
function getVisibleFields(cells: Record<string, MatrixCell | undefined>): string[] {
  const hasAnyQuote = Object.values(cells).some(
    (c) => c && c.confidence_state !== "gap",
  );
  const present = new Set<string>(hasAnyQuote ? ALWAYS_SHOW_FIELDS : []);
  const specFields = new Set<string>();

  for (const cell of Object.values(cells)) {
    if (!cell) continue;
    if (cell.payment_terms) present.add("payment_terms");
    if (cell.warranty) present.add("warranty");
    if (cell.validity_days) present.add("validity_days");
    if (cell.valid_until) present.add("valid_until");
    for (const key of Object.keys(cell.extra_fields ?? {})) {
      specFields.add(key);
    }
  }

  const ordered = (STANDARD_FIELD_ORDER as readonly string[]).filter((f) =>
    present.has(f),
  );
  return [...ordered, ...Array.from(specFields).sort()];
}

export function MatrixPane({
  projectId,
  params,
  onOpenSource,
}: {
  projectId: string;
  params: MatrixParams;
  onOpenSource: (documentId: string) => void;
}) {
  const matrix = useQuery({
    queryKey: ["matrix", projectId, params],
    queryFn: () => api.getMatrix(projectId, params),
  });

  if (matrix.isLoading)
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="skeleton h-16" />
          ))}
        </div>
        <div className="skeleton h-64" />
      </div>
    );
  if (matrix.error)
    return <p className="p-4 text-sm text-gap">Failed to load matrix.</p>;

  const m = matrix.data!;
  const currency = m.currency;

  async function exportXlsx() {
    const url = api.matrixExportUrl(projectId, params);
    const res = await fetch(url, {
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
    });
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `matrix-${projectId}.xlsx`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        <Summary label="Lines" value={String(m.summary.lines_total)} />
        <Summary label="Suppliers" value={String(m.summary.suppliers_total)} />
        <Summary label="Docs parsed" value={String(m.summary.docs_parsed)} />
        <Summary
          label="Lowest landed"
          value={formatCurrency(m.summary.lowest_landed, currency)}
          highlight
        />
        <Summary label="Spread" value={formatPct(m.summary.overall_spread_pct)} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {m.summary.fields_needing_review > 0 && (
          <Badge variant="verify">
            {m.summary.fields_needing_review} to verify
          </Badge>
        )}
        <div className="ml-auto">
          <Button size="sm" variant="outline" onClick={exportXlsx}>
            <Download className="h-4 w-4" /> Export XLSX
          </Button>
        </div>
      </div>

      <div className="overflow-auto rounded-xl border border-border/60 bg-card shadow-soft">
        <table className="w-full border-collapse text-sm" data-testid="matrix-table">
          <thead>
            <tr className="bg-muted/50">
              <th className="sticky left-0 z-10 bg-muted px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                BOM line
              </th>
              {m.suppliers.map((s) => (
                <th key={s.id} className="min-w-[9rem] px-3 py-2.5 text-left font-semibold">
                  {s.name}
                  {s.country && (
                    <span className="ml-1 text-xs font-normal text-muted-foreground">
                      {s.country}
                    </span>
                  )}
                </th>
              ))}
              {m.suppliers.length === 0 && (
                <th className="px-3 py-2.5 text-left font-normal text-muted-foreground">
                  No suppliers yet
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {m.rows.map((row) => {
              const visibleFields = getVisibleFields(row.cells);
              return (
                <tr
                  key={row.bom_item_id}
                  className="border-t border-border/60 transition-colors hover:bg-muted/30"
                >
                  <td className="sticky left-0 z-10 bg-card px-3 py-2">
                    <div className="font-medium">
                      {row.line_no}. {row.part_name}
                    </div>
                    {row.spec_requirement && (
                      <div className="text-xs text-muted-foreground">
                        {row.spec_requirement}
                      </div>
                    )}
                    {visibleFields.length > 0 && (
                      <div className="mt-1.5 space-y-0.5 border-t border-border/40 pt-1.5">
                        {visibleFields.map((f) => (
                          <div
                            key={f}
                            className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/60"
                          >
                            {getFieldLabel(f)}
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                  {m.suppliers.map((s) => {
                    const cell = row.cells[s.id];
                    return (
                      <td key={s.id} className="p-1">
                        <MatrixCellView
                          cell={cell}
                          currency={currency}
                          onOpenSource={onOpenSource}
                          visibleFields={visibleFields}
                        />
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            {m.rows.length === 0 && (
              <tr>
                <td
                  className="px-3 py-6 text-center text-sm text-muted-foreground"
                  colSpan={Math.max(1, m.suppliers.length + 1)}
                >
                  Add BOM lines or upload a priced quotation in Inbox — BOM
                  rows are created automatically when none exist yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Summary({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border/60 bg-card px-3 py-2.5 shadow-soft",
        highlight && "border-teal/30 bg-teal/5",
      )}
    >
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          "mt-0.5 truncate font-data text-base font-semibold tabular-nums",
          highlight && "text-teal",
        )}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

function MatrixCellView({
  cell,
  currency,
  onOpenSource,
  visibleFields,
}: {
  cell: MatrixCell | undefined;
  currency: string;
  onOpenSource: (documentId: string) => void;
  visibleFields: string[];
}) {
  const isGap = !cell || cell.confidence_state === "gap";

  const metaSection = visibleFields.length > 0 ? (
    <div className="mt-1.5 w-full space-y-0.5 border-t border-border/40 pt-1.5">
      {visibleFields.map((field) => {
        // Even gap cells can carry moq/lead_time from quotes that have no price,
        // so always try to read the value and only fall back to null for missing cells.
        const val = cell ? getFieldValue(cell, field) : null;
        const isEmpty = !val || val === "—";
        return (
          <div
            key={field}
            className={cn(
              "text-[10px] tabular-nums",
              isEmpty
                ? "text-muted-foreground/40"
                : field === "warranty"
                  ? "font-medium text-ok"
                  : "font-medium text-foreground",
            )}
          >
            {isEmpty ? "—" : val}
          </div>
        );
      })}
    </div>
  ) : null;

  if (isGap) {
    return (
      <div
        tabIndex={0}
        className={cn(
          "flex flex-col rounded border px-2 py-1.5 text-xs",
          cellStateClass("gap"),
        )}
      >
        <div className="flex min-h-[2.5rem] items-center justify-center text-muted-foreground">
          —
        </div>
        {metaSection}
      </div>
    );
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          tabIndex={0}
          className={cn(
            "flex w-full flex-col rounded border px-2 py-1.5 text-left outline-none focus:ring-2 focus:ring-ring/30",
            cellStateClass(cell.confidence_state),
          )}
        >
          <span className="flex items-center gap-1 font-data font-semibold tabular-nums">
            {formatCurrency(cell.landed, currency)}
            {cell.best_value && (
              <Star className="h-3.5 w-3.5 fill-ok text-ok" aria-label="Best value" />
            )}
          </span>
          <span className="text-xs text-muted-foreground">
            FOB {formatCurrency(cell.fob, currency)}
          </span>
          {metaSection}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-72 text-sm">
        <div className="mb-2 flex items-center justify-between">
          <span className="font-semibold">Quote details</span>
          <Badge variant={cell.confidence_state}>
            {cellStateLabel(cell.confidence_state)}
          </Badge>
        </div>
        <dl className="space-y-1.5">
          <DetailRow k="Landed" v={formatCurrency(cell.landed, currency)} bold />
          <DetailRow k="FOB" v={formatCurrency(cell.fob, currency)} />
          {cell.duty_source === "statutory" && cell.duty != null && (
            <DetailRow
              k={`Duty${cell.hs_code ? ` (HS ${cell.hs_code})` : ""}`}
              v={formatCurrency(cell.duty, currency)}
            />
          )}
          {cell.duty_source === "flat" && (cell.duty ?? 0) > 0 && (
            <DetailRow
              k="Duty (flat assumption)"
              v={formatCurrency(cell.duty, currency)}
            />
          )}
          {cell.moq != null && (
            <DetailRow k="MOQ" v={formatNumber(cell.moq)} />
          )}
          {cell.lead_time_days != null && (
            <DetailRow k="Lead time" v={`${cell.lead_time_days} days`} />
          )}
          {cell.incoterms && (
            <DetailRow k="Incoterms" v={cell.incoterms} />
          )}
          {cell.payment_terms && (
            <DetailRow k="Payment" v={cell.payment_terms} />
          )}
          {cell.validity_days && (
            <DetailRow k="Valid for" v={cell.validity_days} />
          )}
          {cell.valid_until && (
            <DetailRow k="Valid until" v={cell.valid_until} />
          )}
          {cell.warranty && (
            <DetailRow k="Warranty" v={cell.warranty} highlight />
          )}
          {Object.entries(cell.extra_fields ?? {}).map(([k, v]) =>
            v ? <DetailRow key={k} k={getFieldLabel(k)} v={v} /> : null,
          )}
        </dl>
        {cell.duty_breakdown && (
          <div className="mt-2 rounded-md border border-border/60 bg-muted/30 p-2">
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Pakistan levy stack (PKR @ {formatNumber(cell.duty_breakdown.fx_rate)}/USD)
            </p>
            <dl className="space-y-0.5 text-xs">
              <DetailRow
                k="Assessed value"
                v={`${formatNumber(cell.duty_breakdown.assessed_value_pkr)} PKR`}
              />
              {cell.duty_breakdown.levies
                .filter((l) => l.amount_pkr > 0)
                .map((l) => (
                  <DetailRow
                    key={l.levy_type}
                    k={`${l.label} (${(l.rate * 100).toFixed(1)}%)`}
                    v={`${formatNumber(l.amount_pkr)} PKR`}
                  />
                ))}
              <DetailRow
                k="Total duty & taxes"
                v={`${formatNumber(cell.duty_breakdown.total_duty_tax_pkr)} PKR`}
                bold
              />
            </dl>
          </div>
        )}
        {cell.document_id && (
          <Button
            size="sm"
            variant="outline"
            className="mt-3 w-full"
            onClick={() => onOpenSource(cell.document_id!)}
          >
            Open source
          </Button>
        )}
      </PopoverContent>
    </Popover>
  );
}

function DetailRow({
  k,
  v,
  bold,
  highlight,
}: {
  k: string;
  v: string;
  bold?: boolean;
  highlight?: boolean;
}) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-muted-foreground">{k}</dt>
      <dd
        className={cn(
          "text-right",
          bold && "font-semibold",
          highlight && "font-medium text-ok",
        )}
      >
        {v}
      </dd>
    </div>
  );
}
