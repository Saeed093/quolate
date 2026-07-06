"""Correlate tenders with the user's existing quotes via embedding similarity.

Uses pgvector cosine distance over document_embeddings, scoped to the owner.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Document,
    DocumentEmbedding,
    LibraryDocument,
    LibraryDocumentEmbedding,
    Project,
    Quote,
    Supplier,
    Tender,
    TenderSource,
)


async def correlate_embedding(
    session: AsyncSession,
    owner_id: uuid.UUID,
    embedding: list[float] | None,
    *,
    top_k: int = 10,
) -> list[dict]:
    """Return the owner's most semantically-similar document embeddings."""
    if embedding is None:
        return []

    distance = DocumentEmbedding.embedding.cosine_distance(embedding)
    stmt = (
        select(DocumentEmbedding, distance.label("distance"), Document, Supplier)
        .join(Project, DocumentEmbedding.project_id == Project.id)
        .join(Document, DocumentEmbedding.document_id == Document.id)
        .join(Supplier, Document.supplier_id == Supplier.id, isouter=True)
        .where(Project.owner_id == owner_id)
        .where(DocumentEmbedding.embedding.is_not(None))
        .order_by(distance)
        .limit(top_k)
    )
    rows = (await session.execute(stmt)).all()

    matches: list[dict] = []
    for emb, dist, doc, supplier in rows:
        # Best (lowest) active unit price on this document, if any.
        quote_row = (
            await session.execute(
                select(Quote)
                .where(Quote.document_id == doc.id, Quote.superseded_by.is_(None))
                .order_by(Quote.unit_price)
                .limit(1)
            )
        ).scalars().first()
        matches.append(
            {
                "document_id": str(doc.id),
                "project_id": str(doc.project_id),
                "supplier": supplier.name if supplier else None,
                "item": (emb.content or "")[:200],
                "unit_price": float(quote_row.unit_price)
                if quote_row and quote_row.unit_price is not None
                else None,
                "currency": quote_row.currency if quote_row else None,
                "date": doc.created_at.date().isoformat() if doc.created_at else None,
                "similarity": round(1.0 - float(dist), 4),
            }
        )
    return matches


async def correlate_tender(
    session: AsyncSession, tender: Tender, *, top_k: int = 10
) -> list[dict]:
    owner_id = (
        await session.execute(
            select(TenderSource.owner_id).where(TenderSource.id == tender.source_id)
        )
    ).scalar_one_or_none()
    if owner_id is None:
        return []
    return await correlate_embedding(
        session, owner_id, tender.embedding, top_k=top_k
    )


async def owner_of_tender(session: AsyncSession, tender: Tender) -> uuid.UUID | None:
    return (
        await session.execute(
            select(TenderSource.owner_id).where(TenderSource.id == tender.source_id)
        )
    ).scalar_one_or_none()


async def correlate_library(
    session: AsyncSession,
    owner_id: uuid.UUID,
    embedding: list[float] | None,
    *,
    top_k: int = 10,
) -> list[dict]:
    """Return the owner's library documents most semantically-similar to an embedding."""
    if embedding is None:
        return []

    distance = LibraryDocumentEmbedding.embedding.cosine_distance(embedding)
    stmt = (
        select(LibraryDocumentEmbedding, distance.label("distance"), LibraryDocument)
        .join(
            LibraryDocument,
            LibraryDocumentEmbedding.library_document_id == LibraryDocument.id,
        )
        .where(LibraryDocumentEmbedding.owner_id == owner_id)
        .where(LibraryDocumentEmbedding.embedding.is_not(None))
        .order_by(distance)
        .limit(top_k)
    )
    rows = (await session.execute(stmt)).all()

    matches: list[dict] = []
    for emb, dist, lib_doc in rows:
        matches.append(
            {
                "library_document_id": str(lib_doc.id),
                "filename": lib_doc.original_filename,
                "kind": lib_doc.kind,
                "snippet": (emb.content or "")[:200],
                "similarity": round(1.0 - float(dist), 4),
            }
        )
    return matches


async def correlate_tender_against_library(
    session: AsyncSession, tender: Tender, *, top_k: int = 10
) -> list[dict]:
    """Correlate a tender against the owner's global document library."""
    owner_id = await owner_of_tender(session, tender)
    if owner_id is None:
        return []
    return await correlate_library(session, owner_id, tender.embedding, top_k=top_k)
