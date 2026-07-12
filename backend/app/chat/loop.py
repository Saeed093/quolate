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
    own message, or be one arithmetic step away from such numbers (sum,
    difference, product, ratio or percentage of two source figures — covers
    totals, deltas and markups). Anything else is regenerated once; the
    reminder steers the model to the `calculate` tool, whose results count as
    tool results and therefore pass the guard.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass

from app.chat.tools import ChatContext, Tool, _tool_get_matrix, build_registry
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
    "first. For any question about prices or suppliers, call get_matrix first. "
    "Do arithmetic with the calculate tool, never in your head.\n"
    "Available tools:\n{tools}"
)

_NUMBERS_REMINDER = (
    "Your last answer contained a number that did not come from any tool result. "
    "Use the calculate tool to compute it from verified figures, e.g. "
    '{"action": "calculate", "args": {"expression": "5 * 100.0"}}, or call '
    "get_matrix for pricing data. Then answer using only verified numbers. "
    "Respond with one JSON object."
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


def _normalize_num(token: str) -> set[str]:
    """Return a set of equivalent string representations of a number token.

    Handles float precision differences: "145.00" and "145.0" and "145" are all
    equivalent and should match any of each other in the allowed string.
    """
    candidates = {token}
    try:
        f = float(token)
        candidates.add(str(f))           # "145.0"
        candidates.add(str(int(f)) if f == int(f) else str(f))  # "145" when whole
        # Common 2-decimal representation
        candidates.add(f"{f:.2f}")       # "145.00"
        candidates.add(f"{f:.1f}")       # "145.0"
    except (ValueError, OverflowError):
        pass
    return candidates


# Guard against O(n^2) blowup when tool results contain very many numbers.
_MAX_SOURCE_NUMBERS = 150


def _source_numbers(allowed_norm: str) -> list[float]:
    values: set[float] = set()
    for m in _NUMBER_RE.findall(allowed_norm):
        token = m.rstrip(".")
        try:
            values.add(float(token))
        except ValueError:
            continue
        if len(values) >= _MAX_SOURCE_NUMBERS:
            break
    return list(values)


def _derived_values(allowed_norm: str) -> set[float]:
    """All values one arithmetic step away from any pair of source numbers.

    Covers the sums, differences, products, ratios and percentage forms a model
    legitimately derives from tool data (5 units x 100.0 = 500, 10% markup,
    price deltas) without letting arbitrary hallucinated figures through.
    """
    src = _source_numbers(allowed_norm)
    out: set[float] = set(src)
    for i, a in enumerate(src):
        for b in src[i:]:
            out.add(a + b)
            out.add(a - b)
            out.add(b - a)
            out.add(a * b)
            if b:
                out.add(a / b)
            if a:
                out.add(b / a)
            # Percentage forms: b% of a, a plus/minus b% (and vice versa).
            out.add(a * b / 100.0)
            out.add(a * (1 + b / 100.0))
            out.add(a * (1 - b / 100.0))
            out.add(b * (1 + a / 100.0))
            out.add(b * (1 - a / 100.0))
    return out


def _matches_derived(token: str, derived: set[float]) -> bool:
    """Match at the precision the answer displayed: "500" matches 500.0004."""
    try:
        x = float(token)
    except ValueError:
        return False
    decimals = len(token.split(".")[1]) if "." in token else 0
    target = round(x, decimals)
    return any(round(v, decimals) == target for v in derived)


def _numbers_sourced(text: str, allowed: str) -> bool:
    """Return True if every number in *text* is sourced from *allowed*.

    A number is sourced when it appears verbatim in the allowed corpus (with
    float-normalised matching so "145.00" matches "145.0"), or is one
    arithmetic step away from two source numbers (see _derived_values).
    """
    allowed_norm = allowed.replace(",", "")
    derived: set[float] | None = None  # computed lazily on first miss
    for m in _NUMBER_RE.findall(text or ""):
        token = m.replace(",", "").rstrip(".")
        if not token or token == ".":
            continue
        # Check all normalised forms; pass if any variant appears in allowed.
        if any(candidate in allowed_norm for candidate in _normalize_num(token)):
            continue
        if derived is None:
            derived = _derived_values(allowed_norm)
        if not _matches_derived(token, derived):
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

    # When inside a project workbench, always inject the current matrix so the
    # LLM has verified pricing data from the first turn without needing to call
    # get_matrix explicitly.  Numbers from this blob are added to
    # tool_results_text so the numbers-guard accepts them and their arithmetic
    # derivatives (sums, averages, comparisons).
    if ctx.project is not None:
        try:
            matrix = await _tool_get_matrix(ctx)
            matrix_blob = json.dumps(matrix, default=str)
            tool_results_text.append(matrix_blob)
            tool_calls_record.append({"action": "get_matrix", "args": {"auto": True}})
            yield {"type": "tool_call", "action": "get_matrix", "args": {"auto": True}}
            yield {"type": "tool_result", "action": "get_matrix", "result": matrix}
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "CONTEXT[get_matrix] — current comparison matrix for this "
                        "project. All prices and figures below are authoritative; "
                        "you may quote them directly and perform arithmetic on them.\n"
                        + matrix_blob[:8000]
                    ),
                }
            )
        except Exception:
            log.warning("Auto-inject matrix failed; continuing without", exc_info=True)

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
    total_timeout = settings.llm_request_timeout_seconds * 2.5  # total budget for all iterations (~12.5min for 6 iterations)
    last_unparseable = ""

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
                    elif step2.kind == "action":
                        # LLM decided to call a tool to get data — hand it to
                        # the action path below instead of finalizing.
                        step = step2
                    else:
                        # Strip numbers from the original answer rather than
                        # showing a confusing "cannot verify" dead-end.
                        text = _NUMBER_RE.sub("[?]", step.text or "")
            if step.kind == "final":
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
                log.warning("tool %s failed", step.action, exc_info=True)
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
