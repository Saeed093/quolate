"""parse_document job: orchestrates ingestion stages with per-stage logging."""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BomItem, Document
from app.ingestion.extract import extract_content
from app.ingestion.llm_extract import extract_fields
from app.ingestion.persist import persist_extraction
from app.jobs.registry import register
from app.llm.json_enforce import SchemaEnforceError
from app.storage import storage


def _log(document: Document, stage: str, info) -> None:
    log = dict(document.stage_log or {})
    log[stage] = info
    document.stage_log = log


@register("parse_document")
async def parse_document(session: AsyncSession, payload: dict) -> None:
    document_id = uuid.UUID(payload["document_id"])
    result = await session.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if document is None:
        return

    document.status = "processing"
    await session.flush()

    try:
        data = await asyncio.to_thread(storage.get, document.storage_key)

        # Stage 1-2: type routing + OCR (blocking -> thread).
        content = await asyncio.to_thread(
            extract_content, document.original_filename, document.mime_type, data
        )
        document.page_count = content.page_count
        document.ocr_used = content.ocr_used
        _log(document, "extract", {"kind": content.kind_detail, "pages": content.page_count})
        await session.flush()

        # Load BOM lines for mapping.
        bom_result = await session.execute(
            select(BomItem).where(BomItem.project_id == document.project_id)
        )
        bom_lines = [
            {
                "line_no": b.line_no,
                "part_name": b.part_name,
                "spec_requirement": b.spec_requirement,
                "quantity": float(b.quantity) if b.quantity is not None else None,
            }
            for b in bom_result.scalars().all()
        ]

        # Stage 3: LLM extraction (blocking -> thread).
        try:
            extraction = await asyncio.to_thread(
                extract_fields, bom_lines, content.full_text
            )
        except SchemaEnforceError as exc:
            # The LLM failed to produce valid JSON twice. Mark as failed so the
            # user sees a retry button — there are no fields to review.
            document.status = "failed"
            document.error = f"LLM extraction failed (schema): {exc}"
            _log(document, "extract_llm", "schema_failed")
            await session.commit()
            return

        _log(document, "extract_llm", {"fields": len(extraction.get("fields", []))})

        # Stage 4-5: persist fields + quotes + embedding.
        needs_review, bom_created = await persist_extraction(
            session, document, extraction, content.pages
        )
        _log(
            document,
            "persist",
            {"needs_review_fields": needs_review, "auto_bom_created": bom_created},
        )

        document.status = "needs_review" if needs_review > 0 else "parsed"
        document.error = None
        await session.commit()
    except Exception as exc:
        await session.rollback()
        # Re-fetch to record failure cleanly.
        result = await session.execute(
            select(Document).where(Document.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if doc is not None:
            doc.status = "failed"
            doc.error = repr(exc)[:2000]
            await session.commit()
