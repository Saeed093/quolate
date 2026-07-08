"""Prompt templates and JSON schemas for LLM extraction."""
from __future__ import annotations

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier_name": {"type": ["string", "null"]},
        "currency": {"type": ["string", "null"]},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line_no": {"type": ["integer", "null"]},
                    "part_name": {"type": "string"},
                    "spec_requirement": {"type": ["string", "null"]},
                    "quantity": {"type": ["number", "null"]},
                    "unit_price": {"type": ["number", "null"]},
                    "notes": {"type": ["string", "null"]},
                },
                "required": ["part_name"],
                "additionalProperties": True,
            },
        },
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "bom_line_no": {"type": ["integer", "null"]},
                    "field_type": {"type": "string"},
                    "value_text": {"type": ["string", "null"]},
                    "value_num": {"type": ["number", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "currency": {"type": ["string", "null"]},
                    "confidence": {"type": "number"},
                    "source_snippet": {"type": ["string", "null"]},
                },
                "required": ["field_type", "confidence"],
                "additionalProperties": True,
            },
        },
    },
    "required": ["fields"],
    "additionalProperties": True,
}

EXTRACTION_SYSTEM = (
    "You are a precise data-extraction engine for import sourcing. "
    "Extract supplier quotation facts from the document text and map them to the "
    "buyer's BOM lines where possible. "
    "CRITICAL: for every priced product line you MUST emit BOTH "
    "(1) a line_items entry with unit_price as a number, AND "
    "(2) a fields entry with field_type=\"unit_price\", value_num set to that "
    "same number, and bom_line_no matching the BOM line (or line_items.line_no). "
    "When the buyer has no BOM yet, populate line_items with every distinct priced "
    "product/service line from the quotation (part_name, spec, qty, unit_price). "
    "Use the same line_no in line_items and in fields.bom_line_no for each row. "
    "Valid field_type values: unit_price, moq, lead_time_days, currency, incoterms, "
    "validity_days, payment_terms, warranty, or spec:<name> for a specification. "
    "For numeric facts set value_num (a number) and unit where relevant. "
    "Always include a confidence between 0 and 1 and the exact source_snippet "
    "(verbatim text from the document) you relied on. "
    "Only report facts present in the text. Return ONLY JSON matching the schema."
)


def build_extraction_messages(bom_lines: list[dict], chunk_text: str) -> list[dict]:
    bom_desc_lines = []
    for b in bom_lines:
        bom_desc_lines.append(
            f"- line {b['line_no']}: {b['part_name']}"
            + (f" | spec: {b['spec_requirement']}" if b.get("spec_requirement") else "")
            + (f" | qty: {b['quantity']}" if b.get("quantity") is not None else "")
        )
    bom_block = "\n".join(bom_desc_lines) if bom_desc_lines else "(no BOM lines yet)"
    bom_hint = (
        "The buyer has no BOM yet — extract line_items for every priced quotation "
        "row and set bom_line_no on each field to match line_items.line_no. "
        "Every priced row MUST also have a fields entry with field_type=unit_price "
        "and value_num set."
        if not bom_desc_lines
        else (
            "Map each quotation price to the matching BOM line number above. "
            "For every matched line emit a fields entry with field_type=unit_price "
            "and value_num (number). Also include line_items with the same prices."
        )
    )

    user = (
        f"BOM lines to map against:\n{bom_block}\n"
        f"{bom_hint}\n\n"
        f"Document text:\n\"\"\"\n{chunk_text}\n\"\"\"\n\n"
        "Return JSON: {\"supplier_name\": str|null, \"currency\": str|null, "
        "\"line_items\": [{\"line_no\": int|null, \"part_name\": str, "
        "\"spec_requirement\": str|null, \"quantity\": number|null, "
        "\"unit_price\": number|null, \"notes\": str|null}], "
        "\"fields\": [{\"bom_line_no\": int|null, \"field_type\": str, "
        "\"value_text\": str|null, \"value_num\": number|null, \"unit\": str|null, "
        "\"currency\": str|null, \"confidence\": number, \"source_snippet\": str|null}]}"
    )
    return [
        {"role": "system", "content": EXTRACTION_SYSTEM},
        {"role": "user", "content": user},
    ]


# Amounts are extracted as VERBATIM STRINGS, not numbers: suppliers mix
# decimal/thousands conventions ("$27.500" meaning 27.50, "8,770.000" meaning
# 8770.00) and an LLM asked to emit plain numbers silently drops or misreads
# the separators. The server parses the verbatim strings deterministically
# (see app.duty.invoice_parse), cross-checking qty x unit_price = line_total.
INVOICE_ITEMS_SCHEMA = {
    "type": "object",
    "properties": {
        "invoice_currency": {"type": ["string", "null"]},
        "freight": {"type": ["number", "string", "null"]},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line_no": {"type": ["integer", "null"]},
                    "description": {"type": "string"},
                    "quantity": {"type": ["number", "string", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "unit_price": {"type": ["number", "string", "null"]},
                    "line_total": {"type": ["number", "string", "null"]},
                },
                "required": ["description"],
                "additionalProperties": True,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": True,
}

INVOICE_ITEMS_SYSTEM = (
    "You are a precise invoice/quotation line-item extraction engine. "
    "Extract each distinct PRODUCT line from the document text: description, "
    "quantity, unit, unit_price, line_total. "
    "Copy quantity, unit_price and line_total EXACTLY as written in the "
    "document, as strings -- keep every digit, comma, dot and currency "
    "symbol unchanged (e.g. \"$27.500\", \"8,770.00\"). Do NOT reformat, "
    "convert, round or strip separators; the caller parses them. "
    "Do NOT emit subtotal, total, tax, discount, freight or shipping rows as "
    "items -- if a freight/shipping charge appears, report its amount "
    "(verbatim string) in the top-level 'freight' field instead. Report the "
    "invoice currency as an ISO code (e.g. USD, CNY) in 'invoice_currency'. "
    "Extract at most 20 items. Only report what is present in the text. "
    "Return ONLY JSON matching the schema, no prose."
)


def build_invoice_items_messages(text: str) -> list[dict]:
    user = (
        f"Document text:\n\"\"\"\n{text}\n\"\"\"\n\n"
        "Return JSON: {\"invoice_currency\": str|null, \"freight\": str|null, "
        "\"items\": [{\"line_no\": int|null, \"description\": str, "
        "\"quantity\": str|null, \"unit\": str|null, "
        "\"unit_price\": str|null, \"line_total\": str|null}]} "
        "with amounts copied verbatim from the document."
    )
    return [
        {"role": "system", "content": INVOICE_ITEMS_SYSTEM},
        {"role": "user", "content": user},
    ]


HS_CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "product_summary": {"type": ["string", "null"]},
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "hs_code": {"type": "string"},
                    "description": {"type": ["string", "null"]},
                    "confidence": {"type": "number"},
                    "reasoning": {"type": ["string", "null"]},
                },
                "required": ["hs_code", "confidence"],
                "additionalProperties": True,
            },
        },
    },
    "required": ["candidates"],
    "additionalProperties": True,
}

HS_CLASSIFY_SYSTEM = (
    "You are a Pakistan customs classification assistant. Given a product "
    "description or an excerpt from a supplier document (invoice, packing "
    "list, spec sheet, etc.), suggest the most likely Pakistan Customs "
    "Tariff (PCT/HS) code(s), formatted like '8517.12.00'. "
    "This is a heuristic best guess to help a human classifier, NOT an "
    "authoritative ruling -- always give a short reasoning so it can be "
    "verified. If one of the ALREADY-INGESTED codes listed below is a close "
    "match, prefer it (the calculator already has rate data for it); "
    "otherwise suggest the closest real PCT code you know and note in the "
    "reasoning that it may not yet be in the system. Return 1-3 candidates "
    "ranked most-likely first, each with a confidence between 0 and 1. "
    "Return ONLY JSON matching the schema, no prose."
)


def build_hs_classify_messages(text: str, known_codes: list[str]) -> list[dict]:
    known_block = ", ".join(known_codes) if known_codes else "(none ingested yet)"
    user = (
        f"Already-ingested HS codes with rate data (prefer these if a close "
        f"match): {known_block}\n\n"
        f"Product description / document excerpt:\n\"\"\"\n{text}\n\"\"\"\n\n"
        "Return JSON: {\"product_summary\": str|null, \"candidates\": "
        "[{\"hs_code\": str, \"description\": str|null, \"confidence\": number, "
        "\"reasoning\": str|null}]}"
    )
    return [
        {"role": "system", "content": HS_CLASSIFY_SYSTEM},
        {"role": "user", "content": user},
    ]
