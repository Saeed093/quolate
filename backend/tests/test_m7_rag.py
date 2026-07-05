"""M7: full-database RAG + global assistant chat tests. LLM/embeddings mocked."""
from __future__ import annotations

import asyncio
import json

from sqlalchemy import select

from app.chat.rag import search_all
from app.db.models import (
    ChatMessage,
    Document,
    DocumentEmbedding,
    LibraryDocument,
    LibraryDocumentEmbedding,
    Project,
    Tender,
    TenderEmbedding,
    TenderSource,
    User,
)
from app.db.session import SessionLocal
from app.llm.embeddings import embed_text
from app.llm.mock import queue_responses


def _drain() -> None:
    from app.jobs.worker import drain

    asyncio.run(drain())


async def _get_user(session) -> User:
    return (
        await session.execute(select(User).where(User.email == "user@example.com"))
    ).scalar_one()


TOPIC = "solar panel installation quotation"


async def _seed_all_sources(session) -> User:
    """Seed one embedded row in every RAG source for the same topic."""
    user = await _get_user(session)
    vec = embed_text(TOPIC)

    project = Project(owner_id=user.id, name="Solar P")
    session.add(project)
    await session.flush()

    doc = Document(
        project_id=project.id,
        kind="quote",
        original_filename="solar.txt",
        storage_key="projects/x/solar.txt",
        sha256="a" * 64,
        status="parsed",
    )
    session.add(doc)
    await session.flush()
    session.add(
        DocumentEmbedding(
            document_id=doc.id, project_id=project.id, content=TOPIC, embedding=vec
        )
    )

    lib = LibraryDocument(
        owner_id=user.id,
        kind="past_quote",
        original_filename="old_solar.pdf",
        storage_key="library/x/old_solar.pdf",
        sha256="b" * 64,
        status="parsed",
    )
    session.add(lib)
    await session.flush()
    session.add(
        LibraryDocumentEmbedding(
            library_document_id=lib.id, owner_id=user.id, content=TOPIC, embedding=vec
        )
    )

    source = TenderSource(
        owner_id=user.id, name="S", base_url="https://example.com", adapter="generic"
    )
    session.add(source)
    await session.flush()
    tender = Tender(
        source_id=source.id,
        tender_no="T-1",
        title=TOPIC,
        raw_text=TOPIC,
        embedding=vec,
    )
    session.add(tender)
    await session.flush()
    session.add(
        TenderEmbedding(tender_id=tender.id, content=TOPIC, embedding=vec)
    )

    session.add(
        ChatMessage(
            owner_id=user.id,
            project_id=None,
            role="user",
            content=f"we discussed the {TOPIC} before",
            embedding=embed_text(f"we discussed the {TOPIC} before"),
        )
    )
    await session.commit()
    return user


def test_search_all_covers_all_sources(auth_client):
    async def _run():
        async with SessionLocal() as session:
            user = await _seed_all_sources(session)
            hits = await search_all(
                session, user.id, embed_text(TOPIC), top_k=25
            )
            return {h["type"] for h in hits}

    types = asyncio.run(_run())
    assert {"tender", "tender_text", "quote_document", "library_document", "chat"} <= types


def test_index_tender_job_creates_chunks(auth_client):
    async def _seed():
        async with SessionLocal() as session:
            user = await _get_user(session)
            source = TenderSource(
                owner_id=user.id,
                name="S2",
                base_url="https://example.com",
                adapter="generic",
            )
            session.add(source)
            await session.flush()
            tender = Tender(
                source_id=source.id,
                tender_no="T-IDX",
                title="Road works tender",
                raw_text="Construction of access road including drainage works.",
            )
            session.add(tender)
            await session.flush()
            from app.jobs import queue

            await queue.enqueue(session, "index_tender", {"tender_id": str(tender.id)})
            await session.commit()
            return tender.id

    tender_id = asyncio.run(_seed())
    _drain()

    async def _check():
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(TenderEmbedding).where(TenderEmbedding.tender_id == tender_id)
                )
            ).scalars().all()
            return rows

    rows = asyncio.run(_check())
    assert len(rows) >= 1
    assert all(r.tender_document_id is None for r in rows)
    assert all(r.embedding is not None for r in rows)


def test_embed_chat_message_job(auth_client):
    async def _seed():
        async with SessionLocal() as session:
            user = await _get_user(session)
            msg = ChatMessage(
                owner_id=user.id,
                project_id=None,
                role="user",
                content="What was our best price for 66KV transformers last year?",
            )
            session.add(msg)
            await session.flush()
            from app.jobs import queue

            await queue.enqueue(
                session, "embed_chat_message", {"chat_message_id": str(msg.id)}
            )
            await session.commit()
            return msg.id

    msg_id = asyncio.run(_seed())
    _drain()

    async def _check():
        async with SessionLocal() as session:
            msg = (
                await session.execute(
                    select(ChatMessage).where(ChatMessage.id == msg_id)
                )
            ).scalar_one()
            return msg.embedding is not None

    assert asyncio.run(_check())


def test_global_chat_endpoint(auth_client):
    queue_responses(json.dumps({"final": "Hello! I can see your whole database."}))

    resp = auth_client.post("/chat", json={"message": "hello assistant"})
    assert resp.status_code == 200
    assert '"type": "final"' in resp.text or '"type":"final"' in resp.text

    history = auth_client.get("/chat").json()
    roles = [m["role"] for m in history]
    assert "user" in roles and "assistant" in roles
    assert all(m["project_id"] is None for m in history)

    async def _check():
        async with SessionLocal() as session:
            user = await _get_user(session)
            rows = (
                await session.execute(
                    select(ChatMessage).where(
                        ChatMessage.owner_id == user.id,
                        ChatMessage.project_id.is_(None),
                    )
                )
            ).scalars().all()
            return len(rows)

    assert asyncio.run(_check()) >= 2


def test_global_chat_excludes_project_tools(auth_client):
    """The global assistant must not advertise or execute project-scoped tools."""
    from app.chat.tools import build_registry

    global_registry = build_registry(include_project_tools=False)
    assert "get_matrix" not in global_registry
    assert "recompute_landed_cost" not in global_registry
    assert "draft_supplier_email" not in global_registry
    assert "search_knowledge" in global_registry
    assert "search_tenders" in global_registry

    project_registry = build_registry(include_project_tools=True)
    assert "get_matrix" in project_registry
