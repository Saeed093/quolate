"""parse_document job: orchestrates ingestion stages with per-stage logging.

Each stage commits before the next begins so a polling client can observe the
document move through phases (the bar + ETA in the inbox). This is safe because
the session is configured with expire_on_commit=False.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from functools import partial

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import BomItem, Document
from app.ingestion import progress
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


def _set_timing(document: Document, **fields) -> None:
    log = dict(document.stage_log or {})
    timing = dict(log.get("_timing") or {})
    timing.update(fields)
    log["_timing"] = timing
    document.stage_log = log


@register("parse_document")
async def parse_document(session: AsyncSession, payload: dict) -> None:
    document_id = uuid.UUID(payload["document_id"])
    result = await session.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if document is None:
        return

    started_at = datetime.now(timezone.utc)
    document.status = "processing"
    _set_timing(document, **progress.new_timing(started_at, phase="extracting"))

    try:
        data = await asyncio.to_thread(storage.get, document.storage_key)

        # The uploader's OCR language choice (if any) rides on the document;
        # None uses the default.
        ocr_langs = (
            [x.strip() for x in document.ocr_langs.split(",") if x.strip()]
            if document.ocr_langs
            else None
        )
        langs_count = len(ocr_langs or settings.ocr_default_langs_list)
        # Commit the initial estimate so "processing" + a first ETA are visible
        # before the (potentially slow) extraction begins.
        _set_timing(
            document,
            est_total_seconds=progress.estimate_initial_seconds(
                document.original_filename,
                document.mime_type,
                len(data),
                langs_count,
            ),
        )
        await session.commit()

        # Stage 1-2: type routing + OCR (blocking -> thread).
        content = await asyncio.to_thread(
            partial(
                extract_content,
                document.original_filename,
                document.mime_type,
                data,
                ocr_langs=ocr_langs,
            )
        )
        document.page_count = content.page_count
        document.ocr_used = content.ocr_used
        _log(document, "extract", {"kind": content.kind_detail, "pages": content.page_count})
        # OCR is now behind us; refine the estimate from real elapsed + the LLM
        # and persist work still ahead, and advance to the "reading" phase.
        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
        _set_timing(
            document,
            phase="reading",
            est_total_seconds=progress.estimate_remaining_after_extract(
                elapsed, len(content.full_text)
            ),
        )
        await session.commit()

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
        _set_timing(document, phase="saving")
        await session.commit()

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
