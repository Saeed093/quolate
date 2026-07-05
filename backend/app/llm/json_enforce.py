"""Parse + schema-enforce LLM JSON output with a single repair round-trip."""
from __future__ import annotations

import json
import re

from jsonschema import ValidationError, validate

from app.llm.client import LLMClient


class SchemaEnforceError(Exception):
    """Raised when the model cannot produce schema-valid JSON after one repair."""


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict | list:
    """Best-effort extraction of a JSON object/array from model text."""
    text = text.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fallback: grab the first balanced {...} or [...] span.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    raise json.JSONDecodeError("no JSON found", text, 0)


def complete_json(
    client: LLMClient,
    messages: list[dict],
    schema: dict,
    *,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    think: bool = True,
    timeout: float | None = None,
) -> dict | list:
    """Call the model, parse+validate JSON, repairing once on failure."""

    def _attempt(msgs: list[dict]) -> dict | list:
        raw = client.chat(
            msgs, temperature=temperature, max_tokens=max_tokens, think=think, timeout=timeout
        )
        parsed = extract_json(raw)
        validate(instance=parsed, schema=schema)
        return parsed

    try:
        return _attempt(messages)
    except (json.JSONDecodeError, ValidationError) as first_err:
        repair = messages + [
            {
                "role": "user",
                "content": (
                    "Your previous response was not valid JSON matching the "
                    "required schema. Return ONLY valid JSON matching this schema, "
                    "with no prose or code fences:\n"
                    + json.dumps(schema)
                    + f"\n\nError: {first_err}"
                ),
            }
        ]
        try:
            return _attempt(repair)
        except (json.JSONDecodeError, ValidationError) as second_err:
            raise SchemaEnforceError(str(second_err)) from second_err
