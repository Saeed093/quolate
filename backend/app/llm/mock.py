"""In-process mock LLM client (LLM_BASE_URL=mock).

Tests script responses with `queue_responses(...)`. When the queue is empty a
safe default (empty extraction) is returned so pipelines never crash.
"""
from __future__ import annotations

import json

_QUEUE: list[str] = []


def queue_responses(*responses: str) -> None:
    _QUEUE.extend(responses)


def reset_mock() -> None:
    _QUEUE.clear()


def _default_response(messages: list[dict]) -> str:
    return json.dumps({"fields": []})


class MockLLMClient:
    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
        think: bool = True,
        timeout: float | None = None,
    ) -> str:
        if _QUEUE:
            return _QUEUE.pop(0)
        return _default_response(messages)
