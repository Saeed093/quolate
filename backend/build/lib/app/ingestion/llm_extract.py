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


def extract_fields(bom_lines: list[dict], full_text: str) -> dict:
    """Return {'supplier_name', 'currency', 'fields': [...]} merged across chunks."""
    client = get_llm_client()
    # ~3 chars per token, leave headroom for the prompt scaffolding.
    max_chars = max(1000, settings.llm_num_ctx * 3 - 2000)
    chunks = _chunk_text(full_text, max_chars)

    merged_fields: list[dict] = []
    supplier_name: str | None = None
    currency: str | None = None

    for chunk in chunks:
        messages = build_extraction_messages(bom_lines, chunk)
        result = complete_json(
            client,
            messages,
            EXTRACTION_SCHEMA,
            think=not settings.llm_disable_thinking_for_fast_calls,
            timeout=settings.llm_fast_timeout_seconds,
        )
        if isinstance(result, list):
            result = {"fields": result}
        supplier_name = supplier_name or result.get("supplier_name")
        currency = currency or result.get("currency")
        for f in result.get("fields", []) or []:
            if isinstance(f, dict) and f.get("field_type"):
                merged_fields.append(f)

    return {
        "supplier_name": supplier_name,
        "currency": currency,
        "fields": merged_fields,
    }
