"""Parse clipboard TSV (pasted from Excel) into BOM item dicts.

Pure, dependency-light, and unit-tested. Handles:
- optional header row (auto-detected or forced via has_header)
- header-name mapping OR positional mapping
  (part_name, spec_requirement, quantity, target_price, notes)
- numeric cleaning: strips currency symbols, thousands separators, units
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_HEADER_ALIASES = {
    "part_name": {"part", "part name", "item", "description", "name", "part_name"},
    "spec_requirement": {"spec", "specification", "spec requirement", "requirement", "specs"},
    "quantity": {"qty", "quantity", "qnty", "count", "units"},
    "target_price": {"target", "target price", "price", "target_price", "unit price", "budget"},
    "notes": {"notes", "note", "remark", "remarks", "comment"},
}

_POSITIONAL = ["part_name", "spec_requirement", "quantity", "target_price", "notes"]

_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _to_decimal(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    match = _NUM_RE.search(raw.replace(",", ""))
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def _split_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip() == "":
            continue
        # Excel uses tabs; tolerate multi-space / comma-only fallback.
        if "\t" in line:
            cells = line.split("\t")
        elif "," in line:
            cells = line.split(",")
        else:
            cells = [line]
        rows.append([c.strip() for c in cells])
    return rows


def _looks_like_header(cells: list[str]) -> bool:
    lowered = [c.lower() for c in cells]
    known = 0
    for cell in lowered:
        for aliases in _HEADER_ALIASES.values():
            if cell in aliases:
                known += 1
                break
    return known >= 2


def _map_header(cells: list[str]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for idx, cell in enumerate(cells):
        c = cell.lower().strip()
        for field, aliases in _HEADER_ALIASES.items():
            if c in aliases:
                mapping[idx] = field
                break
    return mapping


def parse_bom_tsv(text: str, has_header: bool | None = None) -> list[dict]:
    rows = _split_rows(text)
    if not rows:
        return []

    header_map: dict[int, str] | None = None
    start = 0
    detected = _looks_like_header(rows[0])
    use_header = detected if has_header is None else has_header
    if use_header:
        header_map = _map_header(rows[0])
        start = 1
        if not header_map:
            header_map = None  # forced header but unrecognizable -> positional

    items: list[dict] = []
    line_no = 0
    for cells in rows[start:]:
        record: dict[str, object] = {
            "part_name": None,
            "spec_requirement": None,
            "quantity": None,
            "target_price": None,
            "notes": None,
        }
        if header_map:
            for idx, field in header_map.items():
                if idx < len(cells):
                    record[field] = cells[idx]
        else:
            for idx, field in enumerate(_POSITIONAL):
                if idx < len(cells):
                    record[field] = cells[idx]

        part_name = (record["part_name"] or "").strip() if record["part_name"] else ""
        if not part_name:
            continue

        record["quantity"] = _to_decimal(record["quantity"])  # type: ignore[arg-type]
        record["target_price"] = _to_decimal(record["target_price"])  # type: ignore[arg-type]
        for k in ("spec_requirement", "notes"):
            if record[k] is not None and str(record[k]).strip() == "":
                record[k] = None
        record["part_name"] = part_name

        line_no += 1
        record["line_no"] = line_no
        items.append(record)

    return items
