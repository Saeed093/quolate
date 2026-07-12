"""M4 chat workbench tests. LLM + web are mocked (ReAct JSON protocol)."""
from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import select

from app.chat.loop import run_chat
from app.chat.tools import (
    ChatContext,
    _tool_calculate,
    _tool_fetch_url,
    _tool_web_search,
)
from app.chat.web import WebClient, set_web_client
from app.db.models import Project, User
from app.db.session import SessionLocal
from app.llm.mock import queue_responses


class _FakeWeb(WebClient):
    def __init__(self, text: str = "hello world") -> None:
        self._text = text

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        return [
            {"title": f"Result for {query}", "snippet": "snip", "url": "http://ex/1"},
            {"title": "Second", "snippet": "snip2", "url": "http://ex/2"},
        ]

    def fetch(self, url: str, max_chars: int = 8000) -> str:
        return self._text[:max_chars]


@pytest.fixture
def _fake_web():
    set_web_client(_FakeWeb())
    yield
    set_web_client(None)


async def _load_ctx(session, email: str = "user@example.com") -> ChatContext:
    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one()
    project = (
        await session.execute(
            select(Project).where(Project.owner_id == user.id)
        )
    ).scalars().first()
    return ChatContext(session=session, project=project, user=user)


def _setup_project_with_quote(auth_client) -> str:
    pid = auth_client.post("/projects", json={"name": "P"}).json()["id"]
    line = auth_client.post(f"/projects/{pid}/bom", json={"part_name": "Widget A"}).json()[
        "line_no"
    ]
    queue_responses(
        json.dumps(
            {
                "supplier_name": "ACME",
                "currency": "USD",
                "fields": [
                    {
                        "bom_line_no": line,
                        "field_type": "unit_price",
                        "value_num": 100.0,
                        "currency": "USD",
                        "confidence": 0.95,
                        "source_snippet": "Widget A 100",
                    }
                ],
            }
        )
    )
    auth_client.post(
        f"/projects/{pid}/documents",
        files=[("files", ("q.txt", b"Widget A 100 USD", "text/plain"))],
    )
    from app.jobs.worker import drain

    asyncio.run(drain())
    return pid


def test_tool_loop_executes_recompute_and_returns_new_matrix_hash(auth_client):
    _setup_project_with_quote(auth_client)

    queue_responses(
        json.dumps({"action": "recompute_landed_cost", "args": {"duty_pct": 0.2}}),
        json.dumps({"final": "I recomputed the matrix at 20% duty."}),
    )

    async def _run():
        async with SessionLocal() as session:
            ctx = await _load_ctx(session)
            return await run_chat(ctx, [], "recompute at 20 percent duty")

    result = asyncio.run(_run())
    assert result["matrix_changed"] is True
    assert result["matrix_hash"]
    assert any(c["action"] == "recompute_landed_cost" for c in result["tool_calls"])


def test_model_numbers_only_from_tools(auth_client):
    # Global chat (no project): no matrix is auto-injected, so the strict
    # numbers-guard applies. A fabricated number -> rejected & regenerated.
    _setup_project_with_quote(auth_client)

    queue_responses(
        json.dumps({"final": "The cheapest supplier is $500 per unit."}),
        json.dumps({"final": "Let me verify via the matrix before quoting figures."}),
    )

    async def _run():
        async with SessionLocal() as session:
            ctx = await _load_ctx(session)
            ctx.project = None
            return await run_chat(ctx, [], "which supplier is cheapest?")

    result = asyncio.run(_run())
    assert result["regenerated"] is True
    assert "500" not in result["content"]


def test_project_chat_auto_injects_matrix_and_allows_derived_numbers(auth_client):
    # Project chat: the matrix is injected up front (visible as an auto
    # get_matrix tool call) and the guard permits arithmetic derived from it,
    # e.g. 5 x 100.0 = 500 even though "500" never appears in a tool result.
    _setup_project_with_quote(auth_client)

    queue_responses(
        json.dumps({"final": "Five units of Widget A cost $500 in total."})
    )

    async def _run():
        async with SessionLocal() as session:
            ctx = await _load_ctx(session)
            return await run_chat(ctx, [], "what do 5 units of Widget A cost?")

    result = asyncio.run(_run())
    auto_calls = [c for c in result["tool_calls"] if (c.get("args") or {}).get("auto")]
    assert any(c["action"] == "get_matrix" for c in auto_calls)
    assert result["regenerated"] is False
    assert "500" in result["content"]


def test_hallucinated_number_steers_model_to_calculate_tool(auth_client):
    # A figure that is NOT derivable from the matrix or the user's message must
    # still be rejected in project chat. The numbers reminder steers the model
    # to the calculate tool; its result is then a valid source for the answer.
    _setup_project_with_quote(auth_client)

    queue_responses(
        json.dumps({"final": "The total comes to $523.77."}),
        json.dumps({"action": "calculate", "args": {"expression": "5 * 100.0"}}),
        json.dumps({"final": "Five units cost $500.00 in total."}),
    )

    async def _run():
        async with SessionLocal() as session:
            ctx = await _load_ctx(session)
            return await run_chat(ctx, [], "what is the total for the order?")

    result = asyncio.run(_run())
    assert any(e["type"] == "regenerate" for e in result["events"])
    assert any(c["action"] == "calculate" for c in result["tool_calls"])
    assert "523.77" not in result["content"]
    assert "500" in result["content"]


def test_calculate_tool_evaluates_and_rejects_unsafe():
    ctx = ChatContext(None, None, None)
    assert asyncio.run(_tool_calculate(ctx, expression="5 * 100.0"))["result"] == 500.0
    assert asyncio.run(_tool_calculate(ctx, expression="avg(10, 20, 30)"))["result"] == 20.0
    assert asyncio.run(_tool_calculate(ctx, expression="sum([1, 2, 3]) * 1.18"))["result"] == 7.08
    assert asyncio.run(_tool_calculate(ctx, expression="round(100 * (1 + 0.2), 2)"))["result"] == 120.0
    assert "error" in asyncio.run(_tool_calculate(ctx, expression="1 / 0"))
    assert "error" in asyncio.run(_tool_calculate(ctx, expression="__import__('os').getcwd()"))
    assert "error" in asyncio.run(_tool_calculate(ctx, expression="9 ** 9 ** 9"))
    assert "error" in asyncio.run(_tool_calculate(ctx, expression=""))


def test_web_search_tool_returns_results(_fake_web):
    result = asyncio.run(
        _tool_web_search(ChatContext(None, None, None), query="thermal cameras")
    )
    assert len(result["results"]) == 2
    assert "thermal cameras" in result["results"][0]["title"]
    assert result["results"][0]["url"].startswith("http")


def test_fetch_url_truncates_and_extracts_text():
    long_text = "abcd" * 5000  # 20000 chars
    set_web_client(_FakeWeb(text=long_text))
    try:
        result = asyncio.run(
            _tool_fetch_url(ChatContext(None, None, None), url="http://example.com")
        )
    finally:
        set_web_client(None)
    assert len(result["text"]) == 8000
    assert result["url"] == "http://example.com"


def test_loop_terminates_at_max_iterations(auth_client):
    _setup_project_with_quote(auth_client)

    # Always ask for a tool, never finalize -> loop must stop at MAX_ITERATIONS.
    queue_responses(
        *[json.dumps({"action": "list_documents", "args": {}}) for _ in range(20)]
    )

    async def _run():
        async with SessionLocal() as session:
            ctx = await _load_ctx(session)
            return await run_chat(ctx, [], "loop forever")

    result = asyncio.run(_run())
    assert result.get("terminated") is True
    # Exactly MAX_ITERATIONS model-driven tool calls were made (auto-injected
    # context calls such as get_matrix/retrieve_context don't count).
    llm_calls = [c for c in result["tool_calls"] if not (c.get("args") or {}).get("auto")]
    assert len(llm_calls) == 6
