export function formatPkr(value: string | number): string {
  const n = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-PK", {
    style: "currency",
    currency: "PKR",
    maximumFractionDigits: 2,
  }).format(n);
}

export function formatRate(rate: string, rateType: string): string {
  const n = Number(rate);
  if (Number.isNaN(n)) return "—";
  if (rateType === "fixed") return formatPkr(n);
  return `${(n * 100).toFixed(2)}%`;
}

/** "0.05" (fraction) -> "5" (percent display, trimmed). */
export function fractionToPct(fraction: string | number): string {
  const n = Number(fraction);
  if (!Number.isFinite(n)) return "";
  return String(Number((n * 100).toFixed(6)));
}

/** "5" (percent display) -> "0.05" (fraction string for the API). */
export function pctToFraction(pct: string): string {
  const n = Number(pct);
  if (!Number.isFinite(n)) return "0";
  return String(Number((n / 100).toFixed(8)));
}
