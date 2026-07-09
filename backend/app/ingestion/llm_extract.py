"""Stage 3: LLM extraction with schema enforcement + chunking."""
from __future__ import annotations

from app.config import settings
from app.llm.client import get_llm_client
from app.llm.json_enforce import complete_json
from app.llm.prompts import EXTRACTION_SCHEMA, build_extraction_messages


def _chunk_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text] if text.strip() else [""]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        # Prefer to break on a newline boundary near the limit.
        if end < len(text):
            nl = text.rfind("\n", start, end)
            if nl > start:
                end = nl
        chunks.append(text[start:end])
        start = end
    return chunks


def _normalize_extraction(parsed: object) -> object:
    """Coerce the model's response into the expected object shape.

    Some models (especially smaller local ones) occasionally return a bare
    array of line-item dicts or field dicts instead of the full wrapper object.
    Wrapping it here keeps the schema validator happy and avoids wasting a
    full repair round-trip for a trivially fixable response.
    """
    if not isinstance(parsed, list):
        return parsed
    # Heuristic: if items look like line-items (have part_name), treat them
    # as line_items; otherwise treat them as fields.
    if parsed and isinstance(parsed[0], dict) and "part_name" in parsed[0]:
        return {"line_items": parsed, "fields": []}
    return {"line_items": [], "fields": parsed}


def extract_fields(bom_lines: list[dict], full_text: str) -> dict:
    """Return {'supplier_name', 'currency', 'fields': [...]} merged across chunks."""
    client = get_llm_client()
    # ~3 chars per token, leave headroom for the prompt scaffolding.
    max_chars = max(1000, settings.llm_num_ctx * 3 - 2000)
    chunks = _chunk_text(full_text, max_chars)

    merged_fields: list[dict] = []
    merged_line_items: list[dict] = []
    supplier_name: str | None = None
    currency: str | None = None
    seen_lines: set[int] = set()

    for chunk in chunks:
        messages = build_extraction_messages(bom_lines, chunk)
        result = complete_json(
            client,
            messages,
            EXTRACTION_SCHEMA,
            think=not settings.llm_disable_thinking_for_fast_calls,
            timeout=settings.llm_fast_timeout_seconds,
            normalize=_normalize_extraction,
        )
        if isinstance(result, list):
            result = {"fields": result}
        supplier_name = supplier_name or result.get("supplier_name")
        currency = currency or result.get("currency")
        for item in result.get("line_items", []) or []:
            if not isinstance(item, dict) or not item.get("part_name"):
                continue
            line_no = item.get("line_no")
            key = int(line_no) if line_no is not None else len(merged_line_items) + 1
            if key in seen_lines:
                continue
            seen_lines.add(key)
            merged_line_items.append(item)
        for f in result.get("fields", []) or []:
            if isinstance(f, dict) and f.get("field_type"):
                merged_fields.append(f)

    return {
        "supplier_name": supplier_name,
        "currency": currency,
        "line_items": merged_line_items,
        "fields": merged_fields,
    }
