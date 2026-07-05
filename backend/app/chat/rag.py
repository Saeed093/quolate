"""Unified semantic retrieval across the user's whole knowledge base.

Searches three pgvector stores with one query embedding:
  - Tender.embedding            (scraped tenders, scoped via TenderSource.owner_id)
  - DocumentEmbedding.embedding (project quote documents, scoped via Project.owner_id)
  - LibraryDocumentEmbedding    (global "My Documents" library, owner-scoped)

Used both for automatic context injection in the chat loop and for the
`search_knowledge` chat tool.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ChatMessage,
    Document,
    DocumentEmbedding,
    LibraryDocument,
    LibraryDocumentComment,
    LibraryDocumentEmbedding,
    Project,
    Supplier,
    Tender,
    TenderDocument,
    TenderEmbedding,
    TenderSource,
)


async def search_all(
    session: AsyncSession,
    owner_id: uuid.UUID,
    embedding: list[float] | None,
    *,
    top_k: int = 8,
) -> list[dict]:
    """Return the owner's most similar tenders, quote docs and library docs."""
    if embedding is None:
        return []

    hits: list[dict] = []

    # 1. Tenders
    t_dist = Tender.embedding.cosine_distance(embedding)
    t_stmt = (
        select(Tender, t_dist.label("distance"))
        .join(TenderSource, Tender.source_id == TenderSource.id)
        .where(TenderSource.owner_id == owner_id)
        .where(Tender.embedding.is_not(None))
        .order_by(t_dist)
        .limit(top_k)
    )
    for tender, dist in (await session.execute(t_stmt)).all():
        hits.append(
            {
                "type": "tender",
                "id": str(tender.id),
                "tender_no": tender.tender_no,
                "title": tender.title,
                "organization": tender.organization,
                "category": tender.category,
                "city": tender.city,
                "closing_date": tender.closing_date.isoformat()
                if tender.closing_date
                else None,
                "similarity": round(1.0 - float(dist), 4),
            }
        )

    # 2. Project quote documents
    d_dist = DocumentEmbedding.embedding.cosine_distance(embedding)
    d_stmt = (
        select(DocumentEmbedding, d_dist.label("distance"), Document, Supplier)
        .join(Project, DocumentEmbedding.project_id == Project.id)
        .join(Document, DocumentEmbedding.document_id == Document.id)
        .join(Supplier, Document.supplier_id == Supplier.id, isouter=True)
        .where(Project.owner_id == owner_id)
        .where(DocumentEmbedding.embedding.is_not(None))
        .order_by(d_dist)
        .limit(top_k)
    )
    for emb, dist, doc, supplier in (await session.execute(d_stmt)).all():
        hits.append(
            {
                "type": "quote_document",
                "id": str(doc.id),
                "project_id": str(doc.project_id),
                "filename": doc.original_filename,
                "supplier": supplier.name if supplier else None,
                "snippet": (emb.content or "")[:300],
                "similarity": round(1.0 - float(dist), 4),
            }
        )

    # 2b. Tender full-text chunks (detail pages + downloaded tender documents)
    te_dist = TenderEmbedding.embedding.cosine_distance(embedding)
    te_stmt = (
        select(TenderEmbedding, te_dist.label("distance"), Tender, TenderDocument)
        .join(Tender, TenderEmbedding.tender_id == Tender.id)
        .join(TenderSource, Tender.source_id == TenderSource.id)
        .join(
            TenderDocument,
            TenderEmbedding.tender_document_id == TenderDocument.id,
            isouter=True,
        )
        .where(TenderSource.owner_id == owner_id)
        .where(TenderEmbedding.embedding.is_not(None))
        .order_by(te_dist)
        .limit(top_k)
    )
    for emb, dist, tender, tdoc in (await session.execute(te_stmt)).all():
        hits.append(
            {
                "type": "tender_document" if tdoc is not None else "tender_text",
                "id": str(tender.id),
                "tender_no": tender.tender_no,
                "title": tender.title,
                "document_filename": tdoc.filename if tdoc is not None else None,
                "snippet": (emb.content or "")[:300],
                "similarity": round(1.0 - float(dist), 4),
            }
        )

    # 2c. Past chat conversations
    c_dist = ChatMessage.embedding.cosine_distance(embedding)
    c_stmt = (
        select(ChatMessage, c_dist.label("distance"))
        .where(ChatMessage.owner_id == owner_id)
        .where(ChatMessage.embedding.is_not(None))
        .order_by(c_dist)
        .limit(top_k)
    )
    for msg, dist in (await session.execute(c_stmt)).all():
        hits.append(
            {
                "type": "chat",
                "id": str(msg.id),
                "role": msg.role,
                "project_id": str(msg.project_id) if msg.project_id else None,
                "snippet": (msg.content or "")[:300],
                "date": msg.created_at.date().isoformat() if msg.created_at else None,
                "similarity": round(1.0 - float(dist), 4),
            }
        )

    # 3. Library documents ("My Documents")
    l_dist = LibraryDocumentEmbedding.embedding.cosine_distance(embedding)
    l_stmt = (
        select(LibraryDocumentEmbedding, l_dist.label("distance"), LibraryDocument)
        .join(
            LibraryDocument,
            LibraryDocumentEmbedding.library_document_id == LibraryDocument.id,
        )
        .where(LibraryDocumentEmbedding.owner_id == owner_id)
        .where(LibraryDocumentEmbedding.embedding.is_not(None))
        .order_by(l_dist)
        .limit(top_k)
    )
    for emb, dist, lib_doc in (await session.execute(l_stmt)).all():
        hits.append(
            {
                "type": "library_document",
                "id": str(lib_doc.id),
                "filename": lib_doc.original_filename,
                "kind": lib_doc.kind,
                "snippet": (emb.content or "")[:300],
                "similarity": round(1.0 - float(dist), 4),
            }
        )

    # 4. User comments on library documents
    cm_dist = LibraryDocumentComment.embedding.cosine_distance(embedding)
    cm_stmt = (
        select(LibraryDocumentComment, cm_dist.label("distance"), LibraryDocument)
        .join(
            LibraryDocument,
            LibraryDocumentComment.library_document_id == LibraryDocument.id,
        )
        .where(LibraryDocumentComment.owner_id == owner_id)
        .where(LibraryDocumentComment.embedding.is_not(None))
        .order_by(cm_dist)
        .limit(top_k)
    )
    for comment, dist, lib_doc in (await session.execute(cm_stmt)).all():
        hits.append(
            {
                "type": "document_comment",
                "id": str(comment.id),
                "library_document_id": str(lib_doc.id),
                "filename": lib_doc.original_filename,
                "snippet": (comment.content or "")[:300],
                "date": comment.created_at.date().isoformat()
                if comment.created_at
                else None,
                "similarity": round(1.0 - float(dist), 4),
            }
        )

    hits.sort(key=lambda h: h["similarity"], reverse=True)
    return hits[:top_k]
