"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Loader2 } from "lucide-react";
import { api, type MatrixParams } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";

const CURRENCIES = ["USD", "PKR", "CNY", "EUR", "GBP", "AED", "JPY"];

// The rate box expresses "1 USD = <rate> <currency>". USD is the rate-table
// base, so no conversion (or box) is needed when viewing in USD.
const BASE = "USD";

/**
 * Currency selector + editable exchange-rate box for the matrix.
 *
 * The rate is seeded with today's international rate (live, static fallback)
 * and stays editable — the whole matrix re-converts to whatever rate is shown.
 */
export function CurrencyRateBar({
  params,
  onChange,
}: {
  params: MatrixParams;
  onChange: (p: MatrixParams) => void;
}) {
  const currency = params.currency ?? "USD";
  const showRate = currency !== BASE;

  const [rateStr, setRateStr] = useState(
    params.display_rate != null ? String(params.display_rate) : "",
  );
  // True once the user types their own rate — stops us from clobbering it with
  // the live rate when it arrives.
  const [edited, setEdited] = useState(params.display_rate != null);

  const live = useQuery({
    queryKey: ["fx-live", BASE, currency],
    queryFn: () => api.liveFxRate(BASE, currency),
    enabled: showRate,
    staleTime: 60 * 60 * 1000, // one call per hour is plenty
  });

  // Seed the box from the live rate until the user overrides it.
  useEffect(() => {
    if (!showRate || edited || !live.data) return;
    const r = round2(live.data.rate);
    setRateStr(String(r));
    commit(currency, r);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live.data, showRate, edited, currency]);

  function commit(ccy: string, rate: number | undefined) {
    const next: MatrixParams = { ...params, currency: ccy, display_rate: rate };
    // For PKR the display rate is also the PKR/USD rate the duty stack uses, so
    // keep the statutory duty calc consistent with what the user sees.
    next.fx_rate = ccy === "PKR" ? rate : undefined;
    onChange(next);
  }

  function onCurrencyChange(ccy: string) {
    setEdited(false);
    if (ccy === BASE) {
      setRateStr("");
      onChange({ ...params, currency: ccy, display_rate: undefined, fx_rate: undefined });
    } else {
      // Live rate effect will fill the box; clear stale value meanwhile.
      onChange({ ...params, currency: ccy, display_rate: undefined, fx_rate: undefined });
    }
  }

  function onRateBlur() {
    const n = Number(rateStr);
    if (rateStr.trim() === "" || Number.isNaN(n) || n <= 0) return;
    setEdited(true);
    commit(currency, n);
  }

  function resetToLive() {
    if (!live.data) return;
    const r = round2(live.data.rate);
    setEdited(false);
    setRateStr(String(r));
    commit(currency, r);
  }

  const source = edited ? "your rate" : live.data?.source;

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-xl border border-border/60 bg-card/70 p-3 shadow-soft">
      <div className="flex flex-col gap-1">
        <Label className="text-xs text-muted-foreground">Show prices in</Label>
        <select
          className="select-base w-full sm:w-32"
          value={currency}
          onChange={(e) => onCurrencyChange(e.target.value)}
          aria-label="Display currency"
        >
          {CURRENCIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      {showRate && (
        <div className="ml-auto flex flex-col gap-1">
          <Label className="flex items-center gap-2 text-xs text-muted-foreground">
            Exchange rate
            {live.isFetching ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : source ? (
              <Badge variant={source === "live" ? "ok" : "secondary"}>
                {source === "live"
                  ? "live today"
                  : source === "static"
                    ? "offline rate"
                    : "your rate"}
              </Badge>
            ) : null}
          </Label>
          <div className="flex items-center gap-2">
            <span className="whitespace-nowrap text-sm text-muted-foreground">
              1 {BASE} =
            </span>
            <Input
              className="w-28 font-data tabular-nums"
              type="number"
              inputMode="decimal"
              value={rateStr}
              aria-label={`${BASE} to ${currency} rate`}
              onChange={(e) => setRateStr(e.target.value)}
              onBlur={onRateBlur}
            />
            <span className="text-sm font-medium">{currency}</span>
            <button
              type="button"
              onClick={resetToLive}
              disabled={!live.data || live.isFetching}
              title="Reset to today's international rate"
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
              aria-label="Reset to live rate"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
