import { describe, expect, it } from "vitest";
import { formatCurrency, formatNumber, formatPct } from "@/lib/format";

describe("formatCurrency", () => {
  it("formats USD with two decimals", () => {
    expect(formatCurrency(1234.5, "USD")).toBe("$1,234.50");
  });

  it("supports other currencies", () => {
    const eur = formatCurrency(1000, "EUR");
    expect(eur).toContain("1,000");
  });

  it("renders an em dash for null/undefined/NaN", () => {
    expect(formatCurrency(null)).toBe("—");
    expect(formatCurrency(undefined)).toBe("—");
    expect(formatCurrency(NaN)).toBe("—");
  });
});

describe("formatNumber & formatPct", () => {
  it("formats integers with grouping", () => {
    expect(formatNumber(1000000)).toBe("1,000,000");
  });

  it("formats percentages to one decimal", () => {
    expect(formatPct(12.34)).toBe("12.3%");
    expect(formatPct(null)).toBe("—");
  });
});
