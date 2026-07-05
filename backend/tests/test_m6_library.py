"""M6: global document library ("My Documents") tests. LLM/embeddings mocked."""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db.models import (
    LibraryDocument,
    LibraryDocumentEmbedding,
    ProjectLibraryDocument,
    User,
)
from app.db.session import SessionLocal


def _drain() -> None:
    from app.jobs.worker import drain

    asyncio.run(drain())


def _upload(auth_client, name: str = "past_quote.txt", data: bytes = b"Old solar quote 2024"):
    return auth_client.post(
        "/library/documents",
        files=[("files", (name, data, "text/plain"))],
    )


def test_upload_and_dedup(auth_client):
    r1 = _upload(auth_client)
    assert r1.status_code == 200
    body1 = r1.json()
    assert len(body1["created"]) == 1
    assert body1["skipped"] == []

    # Same bytes again -> deduplicated.
    r2 = _upload(auth_client)
    body2 = r2.json()
    assert body2["created"] == []
    assert len(body2["skipped"]) == 1
    assert body2["skipped"][0]["reason"] == "duplicate"

    docs = auth_client.get("/library/documents").json()
    assert len(docs) == 1


def test_parse_job_populates_embeddings(auth_client):
    r = _upload(auth_client, "notes.txt", b"Transformer installation for HAZECO substation")
    doc_id = r.json()["created"][0]["id"]
    _drain()

    async def _check():
        async with SessionLocal() as session:
            doc = (
                await session.execute(
                    select(LibraryDocument).where(LibraryDocument.id == doc_id)
                )
            ).scalar_one()
            embs = (
                await session.execute(
                    select(LibraryDocumentEmbedding).where(
                        LibraryDocumentEmbedding.library_document_id == doc.id
                    )
                )
            ).scalars().all()
            return doc.status, len(embs)

    status, emb_count = asyncio.run(_check())
    assert status == "parsed"
    assert emb_count >= 1


def test_delete_removes_doc(auth_client):
    r = _upload(auth_client, "del.txt", b"to be deleted")
    doc_id = r.json()["created"][0]["id"]
    _drain()

    resp = auth_client.delete(f"/library/documents/{doc_id}")
    assert resp.status_code == 200
    assert auth_client.get("/library/documents").json() == []


def test_link_unlink_project(auth_client):
    pid = auth_client.post("/projects", json={"name": "P"}).json()["id"]
    doc_id = _upload(auth_client, "ref.txt", b"reference doc").json()["created"][0]["id"]

    r = auth_client.post(
        f"/projects/{pid}/library-documents", json={"library_document_id": doc_id}
    )
    assert r.status_code == 200
    assert r.json()["linked"] is True

    # Idempotent second link.
    r2 = auth_client.post(
        f"/projects/{pid}/library-documents", json={"library_document_id": doc_id}
    )
    assert r2.status_code == 200

    linked = auth_client.get(f"/projects/{pid}/library-documents").json()
    assert len(linked) == 1
    assert linked[0]["library_document_id"] == doc_id

    link_id = linked[0]["id"]
    r3 = auth_client.delete(f"/projects/{pid}/library-documents/{link_id}")
    assert r3.status_code == 200
    assert auth_client.get(f"/projects/{pid}/library-documents").json() == []

    # Underlying library doc still exists.
    assert len(auth_client.get("/library/documents").json()) == 1
