"""parse_library_document job: extract content and generate embeddings for library docs."""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LibraryDocument, LibraryDocumentEmbedding
from app.ingestion.chunking import chunk_text
from app.ingestion.extract import extract_content
from app.jobs.registry import register
from app.llm.embeddings import embed_texts
from app.storage import storage


def _log(document: LibraryDocument, stage: str, info) -> None:
    log = dict(document.stage_log or {})
    log[stage] = info
    document.stage_log = log


@register("parse_library_document")
async def parse_library_document(session: AsyncSession, payload: dict) -> None:
    """Extract and embed a library document."""
    library_document_id = uuid.UUID(payload["library_document_id"])
    result = await session.execute(
        select(LibraryDocument).where(LibraryDocument.id == library_document_id)
    )
    document = result.scalar_one_or_none()
    if document is None:
        return

    document.status = "processing"
    await session.flush()

    # Idempotent re-parse (retries/requeues): clear previous chunks first.
    from sqlalchemy import delete

    await session.execute(
        delete(LibraryDocumentEmbedding).where(
            LibraryDocumentEmbedding.library_document_id == document.id
        )
    )

    try:
        # Fetch file from storage.
        data = await asyncio.to_thread(storage.get, document.storage_key)

        # Extract content (OCR if PDF/image).
        content = await asyncio.to_thread(
            extract_content, document.original_filename, document.mime_type, data
        )
        document.page_count = content.page_count
        document.ocr_used = content.ocr_used
        _log(document, "extract", {"kind": content.kind_detail, "pages": content.page_count})
        await session.flush()

        # Chunk text and embed.
        chunks = chunk_text(content.full_text)
        if chunks:
            embeddings = await asyncio.to_thread(embed_texts, chunks)
            for chunk, embedding in zip(chunks, embeddings):
                emb_row = LibraryDocumentEmbedding(
                    library_document_id=document.id,
                    owner_id=document.owner_id,
                    content=chunk,
                    embedding=embedding,
                )
                session.add(emb_row)
            _log(document, "embed", {"chunks": len(chunks)})
        else:
            _log(document, "embed", {"chunks": 0})

        document.status = "parsed"
        document.error = None
        await session.commit()
    except Exception as exc:
        await session.rollback()
        # Re-fetch and mark failed.
        result = await session.execute(
            select(LibraryDocument).where(LibraryDocument.id == library_document_id)
        )
        doc = result.scalar_one_or_none()
        if doc is not None:
            doc.status = "failed"
            doc.error = repr(exc)[:2000]
            await session.commit()
