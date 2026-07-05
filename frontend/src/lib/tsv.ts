// Client-side TSV (Excel clipboard) parser used for BOM paste preview.
// Mirrors the backend positional/header mapping so the preview matches the
// server import. The authoritative parse still happens server-side.

export interface ParsedBomRow {
  part_name: string;
  spec_requirement: string | null;
  quantity: number | null;
  target_price: number | null;
  notes: string | null;
}

const HEADER_ALIASES: Record<keyof Omit<ParsedBomRow, never>, string[]> = {
  part_name: ["part", "part name", "item", "description", "name", "part_name"],
  spec_requirement: ["spec", "specification", "spec requirement", "requirement", "specs"],
  quantity: ["qty", "quantity", "qnty", "count", "units"],
  target_price: ["target", "target price", "price", "target_price", "unit price", "budget"],
  notes: ["notes", "note", "remark", "remarks", "comment"],
};

const POSITIONAL: (keyof ParsedBomRow)[] = [
  "part_name",
  "spec_requirement",
  "quantity",
  "target_price",
  "notes",
];

function toNumber(raw: string | null): number | null {
  if (raw == null) return null;
  const m = raw.replace(/,/g, "").match(/-?\d[\d]*\.?\d*/);
  if (!m) return null;
  const n = Number(m[0]);
  return Number.isNaN(n) ? null : n;
}

function splitRows(text: string): string[][] {
  return text
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n")
    .filter((line) => line.trim() !== "")
    .map((line) => {
      if (line.includes("\t")) return line.split("\t");
      if (line.includes(",")) return line.split(",");
      return [line];
    })
    .map((cells) => cells.map((c) => c.trim()));
}

function looksLikeHeader(cells: string[]): boolean {
  const lowered = cells.map((c) => c.toLowerCase());
  let known = 0;
  for (const cell of lowered) {
    for (const aliases of Object.values(HEADER_ALIASES)) {
      if (aliases.includes(cell)) {
        known += 1;
        break;
      }
    }
  }
  return known >= 2;
}

function mapHeader(cells: string[]): Record<number, keyof ParsedBomRow> {
  const map: Record<number, keyof ParsedBomRow> = {};
  cells.forEach((cell, idx) => {
    const c = cell.toLowerCase().trim();
    for (const [field, aliases] of Object.entries(HEADER_ALIASES)) {
      if (aliases.includes(c)) {
        map[idx] = field as keyof ParsedBomRow;
        break;
      }
    }
  });
  return map;
}

export function parseBomTsv(
  text: string,
  hasHeader?: boolean,
): ParsedBomRow[] {
  const rows = splitRows(text);
  if (rows.length === 0) return [];

  let headerMap: Record<number, keyof ParsedBomRow> | null = null;
  let start = 0;
  const detected = looksLikeHeader(rows[0]);
  const useHeader = hasHeader === undefined ? detected : hasHeader;
  if (useHeader) {
    headerMap = mapHeader(rows[0]);
    start = 1;
    if (Object.keys(headerMap).length === 0) headerMap = null;
  }

  const items: ParsedBomRow[] = [];
  for (const cells of rows.slice(start)) {
    const record: ParsedBomRow = {
      part_name: "",
      spec_requirement: null,
      quantity: null,
      target_price: null,
      notes: null,
    };
    const raw: Record<string, string | null> = {};
    if (headerMap) {
      for (const [idxStr, field] of Object.entries(headerMap)) {
        const idx = Number(idxStr);
        if (idx < cells.length) raw[field] = cells[idx];
      }
    } else {
      POSITIONAL.forEach((field, idx) => {
        if (idx < cells.length) raw[field] = cells[idx];
      });
    }

    const partName = (raw.part_name ?? "").trim();
    if (!partName) continue;
    record.part_name = partName;
    record.spec_requirement = raw.spec_requirement?.trim() || null;
    record.notes = raw.notes?.trim() || null;
    record.quantity = toNumber(raw.quantity ?? null);
    record.target_price = toNumber(raw.target_price ?? null);
    items.push(record);
  }
  return items;
}
