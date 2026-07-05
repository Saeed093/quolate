"""M4 chat workbench tests. LLM + web are mocked (ReAct JSON protocol)."""
from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import select

from app.chat.loop import run_chat
from app.chat.tools import ChatContext, _tool_fetch_url, _tool_web_search
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
    _setup_project_with_quote(auth_client)

    # First a fabricated number with no tool call -> must be rejected & regenerated.
    queue_responses(
        json.dumps({"final": "The cheapest supplier is $500 per unit."}),
        json.dumps({"final": "Let me verify via the matrix before quoting figures."}),
    )

    async def _run():
        async with SessionLocal() as session:
            ctx = await _load_ctx(session)
            return await run_chat(ctx, [], "which supplier is cheapest?")

    result = asyncio.run(_run())
    assert result["regenerated"] is True
    assert "500" not in result["content"]


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
    # Exactly MAX_ITERATIONS tool calls were made.
    assert result["iterations"] == 6
