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
                <th key={s.id} className="min-w-[8rem] px-3 py-2.5 text-left font-semibold">
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
            {m.rows.map((row) => (
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
                </td>
                {m.suppliers.map((s) => {
                  const cell = row.cells[s.id];
                  return (
                    <td key={s.id} className="p-1">
                      <MatrixCellView
                        cell={cell}
                        currency={currency}
                        onOpenSource={onOpenSource}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
            {m.rows.length === 0 && (
              <tr>
                <td
                  className="px-3 py-6 text-center text-sm text-muted-foreground"
                  colSpan={Math.max(1, m.suppliers.length + 1)}
                >
                  Add BOM lines and upload supplier documents to build the matrix.
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
        highlight && "border-primary/25 bg-accent/50",
      )}
    >
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          "mt-0.5 truncate text-base font-semibold tabular-nums",
          highlight && "text-accent-foreground",
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
}: {
  cell: MatrixCell | undefined;
  currency: string;
  onOpenSource: (documentId: string) => void;
}) {
  if (!cell || cell.confidence_state === "gap") {
    return (
      <div
        tabIndex={0}
        className={cn(
          "flex h-full min-h-[3rem] items-center justify-center rounded border text-xs text-muted-foreground",
          cellStateClass("gap"),
        )}
      >
        —
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
          <span className="flex items-center gap-1 font-semibold">
            {formatCurrency(cell.landed, currency)}
            {cell.best_value && (
              <Star className="h-3.5 w-3.5 fill-ok text-ok" aria-label="Best value" />
            )}
          </span>
          <span className="text-xs text-muted-foreground">
            FOB {formatCurrency(cell.fob, currency)}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-64 text-sm">
        <div className="mb-2 flex items-center justify-between">
          <span className="font-semibold">Cell details</span>
          <Badge variant={cell.confidence_state}>
            {cellStateLabel(cell.confidence_state)}
          </Badge>
        </div>
        <dl className="space-y-1">
          <Row k="Landed" v={formatCurrency(cell.landed, currency)} />
          <Row k="FOB" v={formatCurrency(cell.fob, currency)} />
          <Row k="MOQ" v={formatNumber(cell.moq)} />
          <Row
            k="Lead time"
            v={cell.lead_time_days ? `${cell.lead_time_days} days` : "—"}
          />
        </dl>
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

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="font-medium">{v}</dd>
    </div>
  );
}
