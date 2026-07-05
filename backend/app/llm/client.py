"""LLM client seam (OpenAI-compatible). All LLM calls go through here.

TODO(cloud): point LLM_BASE_URL/LLM_API_KEY at any hosted OpenAI-compatible API.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.config import settings


@runtime_checkable
class LLMClient(Protocol):
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
        """Return the assistant message content for the given messages."""


class OpenAICompatClient:
    """Wraps the OpenAI SDK against any OpenAI-compatible endpoint (e.g. Ollama)."""

    def __init__(self, timeout: float | None = None) -> None:
        from openai import OpenAI

        self._timeout = timeout or settings.llm_request_timeout_seconds
        self._client = OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=self._timeout,
        )
        self._model = settings.llm_model

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
        kwargs: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools

        extra_body: dict = {
            "options": {"num_ctx": settings.llm_num_ctx},
        }
        if not think:
            extra_body["think"] = False
        kwargs["extra_body"] = extra_body

        effective_timeout = timeout if timeout is not None else self._timeout
        resp = self._client.chat.completions.create(**kwargs, timeout=effective_timeout)
        return resp.choices[0].message.content or ""


def get_llm_client() -> LLMClient:
    if settings.llm_is_mock:
        from app.llm.mock import MockLLMClient

        return MockLLMClient()
    return OpenAICompatClient()
