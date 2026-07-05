"""Server-side tool loop (ReAct JSON protocol) behind one driver interface.

The model responds with ONE JSON object per turn:
  - to call a tool:  {"action": "<tool>", "args": {...}}
  - to answer:       {"final": "<message>"}

Native OpenAI tool-calling can later be plugged in behind the same `step()`
seam; ReAct is used from the start because 4B models are unreliable at native
tool-calling (spec section 5).

Hard rules enforced here:
  - max 6 iterations
  - any number in the final answer must come from a tool result or the user's
    own message; otherwise the answer is regenerated once.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass

from app.chat.tools import ChatContext, Tool, build_registry
from app.config import settings
from app.llm.client import LLMClient, get_llm_client
from app.llm.json_enforce import extract_json

log = logging.getLogger("quolate.chat")

MAX_ITERATIONS = 6

_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

_SYSTEM_TEMPLATE = (
    "You are Quolate's sourcing copilot. You drive a quotation comparison matrix "
    "through tools and can search the web.\n"
    "CRITICAL RULES:\n"
    "1. Respond with EXACTLY ONE JSON object and nothing else.\n"
    "2. To use a tool: {{\"action\": \"<tool_name>\", \"args\": {{...}}}}.\n"
    "3. To give your final answer: {{\"final\": \"<your message to the user>\"}}.\n"
    "4. NEVER state any price, cost, quantity or other number unless it appeared "
    "in a tool result during this conversation. If you need a number, call a tool "
    "first.\n"
    "Available tools:\n{tools}"
)

_NUMBERS_REMINDER = (
    "Your last answer contained a number that did not come from any tool result. "
    "Either call a tool to obtain the figure, or answer without stating unverified "
    "numbers. Respond with one JSON object."
)

_PROTOCOL_REMINDER = (
    "Your last message was not a single valid JSON object. Respond with exactly "
    'one JSON object: {"action": ...} or {"final": ...}.'
)


@dataclass
class Step:
    kind: str  # "action" | "final" | "unparseable"
    action: str | None = None
    args: dict | None = None
    text: str | None = None
    raw: str = ""


class ReActDriver:
    """Parses a model turn into a Step. The single seam for tool-calling style."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    async def step(self, messages: list[dict]) -> Step:
        raw = await asyncio.to_thread(self._client.chat, messages)
        return self.parse(raw)

    @staticmethod
    def parse(raw: str) -> Step:
        # Strip any inline chain-of-thought (qwen3-style <think> blocks).
        cleaned = _THINK_RE.sub("", raw).strip()
        try:
            parsed = extract_json(cleaned)
        except json.JSONDecodeError:
            return Step(kind="unparseable", text=cleaned, raw=raw)
        if isinstance(parsed, dict):
            if "action" in parsed:
                args = parsed.get("args")
                return Step(
                    kind="action",
                    action=str(parsed["action"]),
                    args=args if isinstance(args, dict) else {},
                    raw=raw,
                )
            if "final" in parsed:
                return Step(kind="final", text=str(parsed["final"]), raw=raw)
        return Step(kind="unparseable", text=cleaned, raw=raw)


def _numbers_sourced(text: str, allowed: str) -> bool:
    allowed_norm = allowed.replace(",", "")
    for m in _NUMBER_RE.findall(text or ""):
        token = m.replace(",", "").rstrip(".")
        if not token or token == ".":
            continue
        if token not in allowed_norm:
            return False
    return True


def _system_prompt(registry: dict[str, Tool]) -> str:
    lines = []
    for tool in registry.values():
        props = tool.parameters.get("properties", {})
        arg_names = ", ".join(props.keys()) if props else "(none)"
        lines.append(f"- {tool.name}({arg_names}): {tool.description}")
    return _SYSTEM_TEMPLATE.format(tools="\n".join(lines))


async def run_chat_stream(
    ctx: ChatContext,
    history: list[dict],
    user_message: str,
    *,
    client: LLMClient | None = None,
):
    """Async generator of chat events (for SSE)."""
    registry = build_registry(include_project_tools=ctx.project is not None)
    driver = ReActDriver(client or get_llm_client())

    tool_results_text: list[str] = [user_message]
    tool_calls_record: list[dict] = []
    messages: list[dict] = [{"role": "system", "content": _system_prompt(registry)}]
    messages.extend(history)

    # Automatic RAG: retrieve relevant items from the user's whole knowledge
    # base (tenders, quote documents, My Documents library) and inject them up
    # front, so the model has the data even if it never calls a tool.
    context_hits: list[dict] = []
    try:
        from app.chat.rag import search_all
        from app.llm.embeddings import embed_text

        query_embedding = await asyncio.wait_for(
            asyncio.to_thread(embed_text, user_message),
            timeout=settings.llm_fast_timeout_seconds,
        )
        hits = await search_all(ctx.session, ctx.user.id, query_embedding, top_k=8)
        context_hits = [h for h in hits if h.get("similarity", 0) >= 0.3]
    except Exception:
        log.warning("RAG context retrieval failed; continuing without", exc_info=True)

    if context_hits:
        blob = json.dumps(context_hits, default=str)
        # Count as a tool result so the numbers-guard accepts figures from it.
        tool_results_text.append(blob)
        tool_calls_record.append({"action": "retrieve_context", "args": {"auto": True}})
        yield {"type": "tool_call", "action": "retrieve_context", "args": {"auto": True}}
        yield {
            "type": "tool_result",
            "action": "retrieve_context",
            "result": {"results": context_hits, "count": len(context_hits)},
        }
        messages.append(
            {
                "role": "user",
                "content": (
                    "CONTEXT[retrieve_context] — items from the user's database "
                    "(tenders, quotes, library documents) relevant to their "
                    "message. Use these when answering:\n" + blob[:6000]
                ),
            }
        )

    messages.append({"role": "user", "content": user_message})

    start_time = time.monotonic()
    total_timeout = settings.llm_request_timeout_seconds * 2.5  # total budget for all iterations
    last_unparseable = "" (~12.5min for 6 iterations)

    for _ in range(MAX_ITERATIONS):
        elapsed = time.monotonic() - start_time
        if elapsed > total_timeout:
            yield {
                "type": "final",
                "content": "Request took too long. Please try again or simplify your request.",
                "tool_calls": tool_calls_record,
                "matrix_changed": ctx.matrix_changed,
                "matrix_hash": ctx.last_matrix_hash,
                "terminated": True,
            }
            return

        try:
            step = await asyncio.wait_for(
                driver.step(messages), timeout=settings.llm_request_timeout_seconds
            )
        except asyncio.TimeoutError:
            log.warning("LLM call timed out after %fs", settings.llm_request_timeout_seconds)
            yield {
                "type": "final",
                "content": "The assistant took too long to respond. Please try again or simplify your request.",
                "tool_calls": tool_calls_record,
                "matrix_changed": ctx.matrix_changed,
                "matrix_hash": ctx.last_matrix_hash,
                "terminated": True,
            }
            return

        # Small local models often answer in plain prose instead of the JSON
        # protocol. If the reply contains no JSON at all, the prose IS the
        # answer — return it instead of burning iterations on reminders.
        if step.kind == "unparseable" and step.text and "{" not in step.text:
            step = Step(kind="final", text=step.text, raw=step.raw)

        if step.kind == "final":
            allowed = "\n".join(tool_results_text)
            regenerated = False
            text = step.text or ""
            if not _numbers_sourced(text, allowed):
                regenerated = True
                yield {"type": "regenerate"}
                messages.append({"role": "assistant", "content": step.raw})
                messages.append({"role": "user", "content": _NUMBERS_REMINDER})
                try:
                    step2 = await asyncio.wait_for(
                        driver.step(messages), timeout=settings.llm_request_timeout_seconds
                    )
                except asyncio.TimeoutError:
                    text = "I could not verify those figures. Please try rephrasing."
                else:
                    if step2.kind == "final" and _numbers_sourced(step2.text or "", allowed):
                        text = step2.text or ""
                    elif step2.kind == "final":
                        # Strip unverified numbers as a last resort.
                        text = _NUMBER_RE.sub("[unverified]", step2.text or "")
                    else:
                        text = "I could not verify those figures. Please try rephrasing."
            yield {
                "type": "final",
                "content": text,
                "tool_calls": tool_calls_record,
                "matrix_changed": ctx.matrix_changed,
                "matrix_hash": ctx.last_matrix_hash,
                "regenerated": regenerated,
            }
            return

        if step.kind == "unparseable":
            log.warning("unparseable model output (protocol reminder sent): %.200s", step.text or "")
            last_unparseable = step.text or ""
            messages.append({"role": "assistant", "content": step.raw})
            messages.append({"role": "user", "content": _PROTOCOL_REMINDER})
            continue

        # Action step.
        tool = registry.get(step.action or "")
        if tool is None:
            result: dict = {"error": f"unknown tool: {step.action}"}
        else:
            try:
                result = await tool.fn(ctx, **(step.args or {}))
            except TypeError as exc:
                result = {"error": f"bad arguments: {exc}"}
            except Exception as exc:  # tools fail soft
                result = {"error": repr(exc)}

        blob = json.dumps(result, default=str)
        tool_results_text.append(blob)
        tool_calls_record.append({"action": step.action, "args": step.args})
        yield {"type": "tool_call", "action": step.action, "args": step.args}
        yield {"type": "tool_result", "action": step.action, "result": result}

        messages.append({"role": "assistant", "content": step.raw})
        messages.append(
            {"role": "user", "content": f"TOOL_RESULT[{step.action}]: {blob[:6000]}"}
        )

    # Exhausted the loop. Salvage the model's last (protocol-violating) text as
    # the answer where possible — better than a dead-end error.
    if last_unparseable.strip():
        allowed = "\n".join(tool_results_text)
        content = last_unparseable.strip()
        if not _numbers_sourced(content, allowed):
            content = _NUMBER_RE.sub("[unverified]", content)
    else:
        content = (
            "I reached the maximum number of reasoning steps. "
            "Please narrow your request."
        )
    yield {
        "type": "final",
        "content": content,
        "tool_calls": tool_calls_record,
        "matrix_changed": ctx.matrix_changed,
        "matrix_hash": ctx.last_matrix_hash,
        "terminated": True,
    }


async def run_chat(
    ctx: ChatContext,
    history: list[dict],
    user_message: str,
    *,
    client: LLMClient | None = None,
) -> dict:
    """Collect the stream into a single result dict (used by tests/non-SSE)."""
    events: list[dict] = []
    final: dict = {}
    async for event in run_chat_stream(ctx, history, user_message, client=client):
        events.append(event)
        if event["type"] == "final":
            final = event
    final["events"] = events
    final["iterations"] = sum(1 for e in events if e["type"] == "tool_call")
    return final
