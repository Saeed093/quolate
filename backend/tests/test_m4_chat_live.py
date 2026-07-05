"""Live chat tool-loop against a running Ollama. Run with: pytest -m llm"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.auth.security import hash_password
from app.db.models import BomItem, Project, Quote, Supplier, User
from app.db.session import SessionLocal


@pytest.mark.llm
def test_live_chat_loop_answers_and_terminates(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "llm_base_url", "http://localhost:11434/v1")
    monkeypatch.setattr(settings, "llm_api_key", "ollama")
    monkeypatch.setattr(settings, "llm_model", "qwen3:8b")

    from app.chat.loop import run_chat
    from app.chat.tools import ChatContext

    async def _run():
        async with SessionLocal() as session:
            user = User(email="chatlive@example.com", password_hash=hash_password("x" * 8))
            session.add(user)
            await session.flush()
            project = Project(owner_id=user.id, name="Live", base_currency="USD")
            session.add(project)
            await session.flush()
            supplier = Supplier(project_id=project.id, name="ACME")
            bom = BomItem(project_id=project.id, line_no=1, part_name="Thermal Camera")
            session.add_all([supplier, bom])
            await session.flush()
            session.add(
                Quote(
                    project_id=project.id,
                    supplier_id=supplier.id,
                    bom_item_id=bom.id,
                    unit_price=1250,
                    currency="USD",
                )
            )
            await session.flush()

            ctx = ChatContext(session=session, project=project, user=user)
            return await run_chat(
                ctx,
                [],
                "Use the get_matrix tool, then tell me the landed cost for the "
                "Thermal Camera.",
            )

    result = asyncio.run(_run())
    assert isinstance(result.get("content"), str)
    assert result["content"].strip() != ""
    assert result["iterations"] <= 6
