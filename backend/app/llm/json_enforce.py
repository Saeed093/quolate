"""Parse + schema-enforce LLM JSON output with a single repair round-trip."""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from jsonschema import ValidationError, validate

from app.llm.client import LLMClient


class SchemaEnforceError(Exception):
    """Raised when the model cannot produce schema-valid JSON after one repair."""


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
# Models sometimes wrap reasoning in <think>…</think> (or similar) before JSON.
_THINK_RE = re.compile(
    r"<(?:think|thinking|reasoning)[^>]*>.*?</(?:think|thinking|reasoning)>",
    re.DOTALL | re.IGNORECASE,
)


def _strip_noise(text: str) -> str:
    text = _THINK_RE.sub("", text)
    return text.strip()


def extract_json(text: str) -> dict | list:
    """Best-effort extraction of a JSON object/array from model text."""
    text = _strip_noise(text or "")
    if not text:
        raise json.JSONDecodeError("no JSON found", text, 0)

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

    # Last resort: find the outermost brace/bracket by scanning.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        if start == -1:
            continue
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
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
    normalize: Callable[[Any], Any] | None = None,
) -> dict | list:
    """Call the model, parse+validate JSON, repairing once on failure.

    Args:
        normalize: Optional callable applied to the parsed value *before*
            schema validation. Use this to coerce known alternative shapes
            (e.g. bare arrays) into the expected object form so they pass
            validation and spare the retry round-trip.
    """

    def _attempt(msgs: list[dict], *, use_think: bool) -> dict | list:
        raw = client.chat(
            msgs,
            temperature=temperature,
            max_tokens=max_tokens,
            think=use_think,
            timeout=timeout,
        )
        if not (raw or "").strip():
            raise json.JSONDecodeError("empty model response", raw or "", 0)
        parsed = extract_json(raw)
        if normalize is not None:
            parsed = normalize(parsed)
        validate(instance=parsed, schema=schema)
        return parsed

    try:
        return _attempt(messages, use_think=think)
    except (json.JSONDecodeError, ValidationError) as first_err:
        repair = messages + [
            {
                "role": "user",
                "content": (
                    "Your previous response was not valid JSON matching the "
                    "required schema. Return ONLY valid JSON matching this schema, "
                    "with no prose, no thinking, and no code fences:\n"
                    + json.dumps(schema)
                    + f"\n\nError: {first_err}"
                ),
            }
        ]
        try:
            # Repair pass: force think=False so the model emits JSON directly.
            return _attempt(repair, use_think=False)
        except (json.JSONDecodeError, ValidationError) as second_err:
            raise SchemaEnforceError(str(second_err)) from second_err
