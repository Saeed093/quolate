"use client";

import { useEffect, useState } from "react";
import type { MatrixParams } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const CURRENCIES = ["USD", "EUR", "GBP", "CNY", "PKR", "AED", "JPY"];

export function AssumptionsStrip({
  params,
  onChange,
}: {
  params: MatrixParams;
  onChange: (p: MatrixParams) => void;
}) {
  // UI shows percentages; params store fractions.
  const [duty, setDuty] = useState(pctString(params.duty_pct));
  const [lc, setLc] = useState(pctString(params.lc_pct));
  const [freight, setFreight] = useState(numString(params.freight_per_unit));
  const [currency, setCurrency] = useState(params.currency ?? "USD");

  useEffect(() => {
    setDuty(pctString(params.duty_pct));
    setLc(pctString(params.lc_pct));
    setFreight(numString(params.freight_per_unit));
    setCurrency(params.currency ?? "USD");
  }, [params.duty_pct, params.lc_pct, params.freight_per_unit, params.currency]);

  function commit(next: Partial<MatrixParams>) {
    onChange({ ...params, ...next });
  }

  return (
    <div className="grid grid-cols-2 items-end gap-3 rounded-xl border border-border/60 bg-card/70 p-3 shadow-soft sm:flex sm:flex-wrap sm:gap-4">
      <Field label="Currency">
        <select
          className="select-base w-full sm:w-28"
          value={currency}
          onChange={(e) => {
            setCurrency(e.target.value);
            commit({ currency: e.target.value });
          }}
          aria-label="Currency"
        >
          {CURRENCIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Duty %">
        <Input
          className="w-full sm:w-24"
          type="number"
          inputMode="decimal"
          value={duty}
          aria-label="Duty percent"
          onChange={(e) => setDuty(e.target.value)}
          onBlur={() => commit({ duty_pct: fracFromPct(duty) })}
        />
      </Field>
      <Field label="Freight / unit">
        <Input
          className="w-full sm:w-28"
          type="number"
          inputMode="decimal"
          value={freight}
          aria-label="Freight per unit"
          onChange={(e) => setFreight(e.target.value)}
          onBlur={() => commit({ freight_per_unit: numFromStr(freight) })}
        />
      </Field>
      <Field label="LC %">
        <Input
          className="w-full sm:w-24"
          type="number"
          inputMode="decimal"
          value={lc}
          aria-label="LC percent"
          onChange={(e) => setLc(e.target.value)}
          onBlur={() => commit({ lc_pct: fracFromPct(lc) })}
        />
      </Field>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function pctString(frac: number | undefined): string {
  if (frac === undefined || frac === null) return "";
  return String(Math.round(frac * 1000) / 10);
}
function numString(n: number | undefined): string {
  if (n === undefined || n === null) return "";
  return String(n);
}
function fracFromPct(s: string): number | undefined {
  const n = Number(s);
  return s.trim() === "" || Number.isNaN(n) ? undefined : n / 100;
}
function numFromStr(s: string): number | undefined {
  const n = Number(s);
  return s.trim() === "" || Number.isNaN(n) ? undefined : n;
}
