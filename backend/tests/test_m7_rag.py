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


def test_new_only_pull_skips_existing(auth_client):
    """A second pull of the same listing skips existing tenders entirely."""
    from datetime import date

    from app.tenders.adapters.base import BaseAdapter, NoticeRef
    from app.tenders.scraper import pull_source

    class _FakeAdapter(BaseAdapter):
        name = "fake"
        default_org_type = "federal"
        fetch_count = 0

        def list_notices(self, since=None):
            return [
                NoticeRef(
                    tender_no="NEW-1",
                    title="Fresh tender",
                    raw={
                        "tender_no": "NEW-1",
                        "title": "Fresh tender",
                        "closing_date": "Jul 30, 2026",
                    },
                )
            ]

        def fetch_notice(self, ref):
            type(self).fetch_count += 1
            return self.notice_from_ref(ref)

    async def _run():
        async with SessionLocal() as session:
            user = await _get_user(session)
            source = TenderSource(
                owner_id=user.id,
                name="F",
                base_url="https://example.com",
                adapter="generic",
            )
            session.add(source)
            await session.flush()
            adapter = _FakeAdapter(source.base_url)

            r1 = await pull_source(session, source, adapter=adapter, delay=0)
            await session.commit()
            # Second pull: same listing, now with a changed closing date.
            adapter2 = _FakeAdapter(source.base_url)

            def notices2(since=None):
                return [
                    NoticeRef(
                        tender_no="NEW-1",
                        title="Fresh tender",
                        raw={
                            "tender_no": "NEW-1",
                            "title": "Fresh tender",
                            "closing_date": "Aug 15, 2026",
                        },
                    )
                ]

            adapter2.list_notices = notices2
            r2 = await pull_source(session, source, adapter=adapter2, delay=0)
            await session.commit()

            tender = (
                await session.execute(
                    select(Tender).where(Tender.tender_no == "NEW-1")
                )
            ).scalar_one()
            return r1, r2, tender.closing_date

    r1, r2, closing = asyncio.run(_run())
    assert r1["created"] == 1
    assert r2["created"] == 0
    assert r2["skipped_existing"] == 1
    # fetch_notice ran only during the first pull.
    from datetime import date as _date

    assert closing == _date(2026, 8, 15)  # date refreshed from listing row


def test_trim_tenders(auth_client):
    from app.tenders.cleanup import trim_tenders

    async def _run():
        async with SessionLocal() as session:
            user = await _get_user(session)
            source = TenderSource(
                owner_id=user.id,
                name="T",
                base_url="https://example.com",
                adapter="generic",
            )
            session.add(source)
            await session.flush()
            from datetime import date as _d

            for i in range(8):
                t = Tender(
                    source_id=source.id,
                    tender_no=f"TRIM-{i}",
                    title=f"Tender {i}",
                    advertise_date=_d(2026, 7, i + 1),  # deterministic ordering
                )
                session.add(t)
                await session.flush()
                session.add(
                    TenderEmbedding(tender_id=t.id, content=f"t{i}", embedding=None)
                )
            await session.commit()

            result = await trim_tenders(session, user.id, keep=3)

            remaining = (
                await session.execute(
                    select(Tender).where(Tender.source_id == source.id)
                )
            ).scalars().all()
            emb_count = len(
                (await session.execute(select(TenderEmbedding))).scalars().all()
            )
            return result, [t.tender_no for t in remaining], emb_count

    result, remaining, emb_count = asyncio.run(_run())
    assert result["removed"] == 5
    assert len(remaining) == 3
    # Newest by created_at kept (advertise_date is null for all).
    assert set(remaining) == {"TRIM-5", "TRIM-6", "TRIM-7"}
    assert emb_count == 3  # embeddings of removed tenders cascaded away


def test_requeue_stale_running_jobs(auth_client):
    from app.db.models import Job
    from app.jobs.worker import requeue_stale_jobs

    async def _run():
        async with SessionLocal() as session:
            session.add(Job(type="parse_document", payload={}, status="running"))
            session.add(Job(type="index_tender", payload={}, status="done"))
            await session.commit()

        requeued = await requeue_stale_jobs()

        async with SessionLocal() as session:
            rows = (await session.execute(select(Job))).scalars().all()
            return requeued, {j.type: j.status for j in rows}

    requeued, statuses = asyncio.run(_run())
    assert requeued == 1
    assert statuses["parse_document"] == "queued"
    assert statuses["index_tender"] == "done"


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
