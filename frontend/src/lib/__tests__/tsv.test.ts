import { describe, expect, it } from "vitest";
import { parseBomTsv } from "@/lib/tsv";

describe("parseBomTsv", () => {
  it("parses tab-separated rows with a detected header", () => {
    const text = [
      "Part\tSpec\tQty\tTarget Price",
      "Thermal Camera\t640x480\t100\t$1,200.00",
      "Tripod\tAluminium\t50\t40",
    ].join("\n");
    const rows = parseBomTsv(text);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      part_name: "Thermal Camera",
      spec_requirement: "640x480",
      quantity: 100,
      target_price: 1200,
    });
    expect(rows[1].target_price).toBe(40);
  });

  it("falls back to positional mapping without a header", () => {
    const text = "Widget A\tSpec A\t10\t5.5";
    const rows = parseBomTsv(text);
    expect(rows).toHaveLength(1);
    expect(rows[0].part_name).toBe("Widget A");
    expect(rows[0].quantity).toBe(10);
    expect(rows[0].target_price).toBe(5.5);
  });

  it("strips currency symbols and thousands separators from numbers", () => {
    const rows = parseBomTsv("Pump\t\t1,500\tPKR 12,345.67");
    expect(rows[0].quantity).toBe(1500);
    expect(rows[0].target_price).toBe(12345.67);
  });

  it("skips rows without a part name and handles commas as fallback", () => {
    const text = "Item,Qty\nBolt,25\n,99";
    const rows = parseBomTsv(text);
    expect(rows).toHaveLength(1);
    expect(rows[0].part_name).toBe("Bolt");
  });

  it("returns an empty array for blank input", () => {
    expect(parseBomTsv("")).toEqual([]);
    expect(parseBomTsv("\n\n")).toEqual([]);
  });
});
