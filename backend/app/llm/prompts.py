"""Prompt templates and JSON schemas for LLM extraction."""
from __future__ import annotations

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier_name": {"type": ["string", "null"]},
        "currency": {"type": ["string", "null"]},
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
    "Valid field_type values: unit_price, moq, lead_time_days, currency, incoterms, "
    "validity_days, payment_terms, or spec:<name> for a specification. "
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
    bom_block = "\n".join(bom_desc_lines) if bom_desc_lines else "(no BOM lines)"

    user = (
        f"BOM lines to map against:\n{bom_block}\n\n"
        f"Document text:\n\"\"\"\n{chunk_text}\n\"\"\"\n\n"
        "Return JSON: {\"supplier_name\": str|null, \"currency\": str|null, "
        "\"fields\": [{\"bom_line_no\": int|null, \"field_type\": str, "
        "\"value_text\": str|null, \"value_num\": number|null, \"unit\": str|null, "
        "\"currency\": str|null, \"confidence\": number, \"source_snippet\": str|null}]}"
    )
    return [
        {"role": "system", "content": EXTRACTION_SYSTEM},
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
