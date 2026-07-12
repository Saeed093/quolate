"""Extract customer requirements (demand line items) from RFP-like sources.

A "source" is anything the customer sent: an already-uploaded project document
(pdf/image/docx), a My-Documents library file, a tender, or raw pasted text
(chat/email). Everything is reduced to text (images via the existing OCR
pipeline — the local model is text-only) and fed to the LLM to produce a list
of requested items, which are persisted as editable ``BomItem`` rows.
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import BomItem, Document, LibraryDocument, Project, Tender, TenderSource
from app.ingestion.extract import extract_content
from app.llm.client import get_llm_client
from app.llm.json_enforce import SchemaEnforceError, complete_json
from app.llm.prompts import REQUIREMENTS_SCHEMA, build_requirements_messages
from app.storage import storage

# Cap the text we feed the model (leave prompt headroom); RFPs are usually short.
_MAX_SOURCE_CHARS = 12000


class RequirementSourceError(Exception):
    """A source could not be loaded or produced no usable text."""


async def _text_from_document(
    session: AsyncSession, project: Project, doc_id: uuid.UUID
) -> str:
    doc = (
        await session.execute(
            select(Document).where(
                Document.id == doc_id, Document.project_id == project.id
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise RequirementSourceError(f"document {doc_id} not found in this project")
    return await _extract_stored(doc.original_filename, doc.mime_type, doc.storage_key)


async def _text_from_library(
    session: AsyncSession, owner_id: uuid.UUID, lib_id: uuid.UUID
) -> str:
    lib = (
        await session.execute(
            select(LibraryDocument).where(
                LibraryDocument.id == lib_id, LibraryDocument.owner_id == owner_id
            )
        )
    ).scalar_one_or_none()
    if lib is None:
        raise RequirementSourceError(f"library document {lib_id} not found")
    return await _extract_stored(lib.original_filename, lib.mime_type, lib.storage_key)


async def _text_from_tender(
    session: AsyncSession, owner_id: uuid.UUID, tender_id: uuid.UUID
) -> str:
    tender = (
        await session.execute(
            select(Tender)
            .join(TenderSource, Tender.source_id == TenderSource.id)
            .where(Tender.id == tender_id, TenderSource.owner_id == owner_id)
        )
    ).scalar_one_or_none()
    if tender is None:
        raise RequirementSourceError(f"tender {tender_id} not found")
    parts = [tender.title, tender.organization, getattr(tender, "description", None)]
    text = "\n".join(p for p in parts if p)
    if not text.strip():
        raise RequirementSourceError("tender has no usable text")
    return text


async def _extract_stored(
    filename: str, mime_type: str | None, storage_key: str
) -> str:
    """Load a stored file and reduce it to text (OCR for images/scans)."""

    def _run() -> str:
        data = storage.get(storage_key)
        content = extract_content(filename, mime_type, data)
        return "\n".join(p.text for p in content.pages if p.text)

    return await asyncio.to_thread(_run)


async def load_source_text(
    session: AsyncSession, project: Project, ref: object
) -> str:
    """Resolve one source ref (schemas.QuotationSourceRef) to plain text."""
    kind = getattr(ref, "kind", None)
    if kind == "text":
        text = (getattr(ref, "text", None) or "").strip()
        if not text:
            raise RequirementSourceError("text source is empty")
        return text
    ref_id = getattr(ref, "id", None)
    if ref_id is None:
        raise RequirementSourceError(f"source kind '{kind}' requires an id")
    if kind == "document":
        return await _text_from_document(session, project, ref_id)
    if kind == "library":
        return await _text_from_library(session, project.owner_id, ref_id)
    if kind == "tender":
        return await _text_from_tender(session, project.owner_id, ref_id)
    raise RequirementSourceError(f"unknown source kind '{kind}'")


def _requirements_from_text(text: str) -> list[dict]:
    """LLM: text -> [{part_name, spec_requirement, quantity, notes}]."""
    client = get_llm_client()
    messages = build_requirements_messages(text[:_MAX_SOURCE_CHARS])
    result = complete_json(
        client,
        messages,
        REQUIREMENTS_SCHEMA,
        think=not settings.llm_disable_thinking_for_fast_calls,
        timeout=settings.llm_fast_timeout_seconds,
    )
    items = result.get("line_items", []) if isinstance(result, dict) else []
    return [i for i in items if isinstance(i, dict) and i.get("part_name")]


async def _next_line_no(session: AsyncSession, project_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(BomItem.line_no), 0)).where(
            BomItem.project_id == project_id
        )
    )
    return int(result.scalar_one()) + 1


async def extract_requirements(
    session: AsyncSession, project: Project, sources: list[object]
) -> list[BomItem]:
    """Extract requested items from all sources and persist them as BomItems.

    Appends to the project's existing BOM (does not clobber). The caller commits.
    Raises RequirementSourceError if no source yields text, or SchemaEnforceError
    if the model cannot produce valid JSON.
    """
    if not sources:
        raise RequirementSourceError("no sources provided")

    texts: list[str] = []
    errors: list[str] = []
    for ref in sources:
        try:
            texts.append(await load_source_text(session, project, ref))
        except RequirementSourceError as exc:
            errors.append(str(exc))
    if not texts:
        raise RequirementSourceError(
            "no source produced usable text: " + "; ".join(errors)
        )

    combined = "\n\n---\n\n".join(texts)
    raw_items = await asyncio.to_thread(_requirements_from_text, combined)
    if not raw_items:
        raise RequirementSourceError(
            "no line items could be extracted from the provided sources"
        )

    line_no = await _next_line_no(session, project.id)
    created: list[BomItem] = []
    for item in raw_items:
        qty = item.get("quantity")
        bom = BomItem(
            project_id=project.id,
            line_no=line_no,
            part_name=str(item["part_name"])[:500],
            spec_requirement=item.get("spec_requirement"),
            quantity=qty if isinstance(qty, (int, float)) else None,
            notes=item.get("notes"),
        )
        session.add(bom)
        created.append(bom)
        line_no += 1
    await session.flush()
    return created
