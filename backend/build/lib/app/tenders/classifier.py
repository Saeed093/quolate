"""LLM classification of a tender against controlled vocabularies.

One LLM call per tender. The model's output is *filtered* against the fixed
vocab lists so only known values can ever be stored.
"""
from __future__ import annotations

from app.llm.client import get_llm_client
from app.llm.json_enforce import SchemaEnforceError, complete_json
from app.tenders.vocab import (
    CATEGORIES,
    ORG_TYPES,
    SECTOR_TAGS,
    normalize_category,
    normalize_org_type,
    normalize_sector_tags,
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "org_type": {"type": ["string", "null"]},
        "category": {"type": ["string", "null"]},
        "sector_tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["sector_tags"],
    "additionalProperties": True,
}


def classify_tender(title: str | None, raw_text: str | None, organization: str | None) -> dict:
    from app.config import settings

    client = get_llm_client()
    body = "\n".join(
        p for p in [title or "", organization or "", (raw_text or "")[:4000]] if p
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You classify Pakistani public-procurement tenders. "
                f"org_type must be one of: {', '.join(ORG_TYPES)}. "
                f"category must be one of: {', '.join(CATEGORIES)}. "
                f"sector_tags must be chosen ONLY from: {', '.join(SECTOR_TAGS)}. "
                "Return ONLY JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Tender:\n\"\"\"\n{body}\n\"\"\"\n\n"
                'Return JSON: {"org_type": str|null, "category": str|null, '
                '"sector_tags": [str]}'
            ),
        },
    ]
    try:
        result = complete_json(
            client,
            messages,
            _SCHEMA,
            think=not settings.llm_disable_thinking_for_fast_calls,
            timeout=settings.llm_fast_timeout_seconds,
        )
    except SchemaEnforceError:
        result = {}
    if not isinstance(result, dict):
        result = {}

    return {
        "org_type": normalize_org_type(result.get("org_type")),
        "category": normalize_category(result.get("category")),
        "sector_tags": normalize_sector_tags(result.get("sector_tags")),
    }
