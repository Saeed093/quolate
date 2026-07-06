"""LLM-based HS/PCT code classification from free text or a library document.

Stateless and synchronous by design (see the plan): the result is only a set
of *suggestions* the user reviews and picks from before calculating -- there
is no persisted classification/review table, unlike the ingested rate rows
in `duty_tax_rates`/`exemption_rules`.
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import DutyTaxRate, LibraryDocument
from app.duty.resolver import GENERAL_HS_CODE
from app.duty.schemas import HsCandidate, HsClassificationOut
from app.ingestion.extract import extract_content
from app.llm.client import get_llm_client
from app.llm.json_enforce import SchemaEnforceError, complete_json
from app.llm.prompts import HS_CLASSIFY_SCHEMA, build_hs_classify_messages
from app.storage import storage

#: Chars of document/free text fed to the LLM -- mirrors the cap used
#: elsewhere for one-off LLM calls (e.g. `fetch_url`).
TEXT_BUDGET = 6000


class ClassificationInputError(Exception):
    """Bad input (no text/doc given, doc missing, doc has no text)."""


async def _load_document_text(
    session: AsyncSession, library_document_id: uuid.UUID, owner_id: uuid.UUID
) -> str:
    """Re-extract text for an already-stored library document.

    No full-text column exists on `LibraryDocument`/`LibraryDocumentEmbedding`
    (only chunk embeddings are persisted), so re-extraction from the stored
    file is the only reliable option here -- acceptable since this is an
    on-demand, one-off call rather than a hot path.
    """
    doc = (
        await session.execute(
            select(LibraryDocument).where(
                LibraryDocument.id == library_document_id,
                LibraryDocument.owner_id == owner_id,
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise ClassificationInputError("Library document not found.")

    try:
        data = await asyncio.to_thread(storage.get, doc.storage_key)
    except FileNotFoundError as exc:
        raise ClassificationInputError("Stored file for this document is missing.") from exc

    content = await asyncio.to_thread(
        extract_content, doc.original_filename, doc.mime_type, data
    )
    text = content.full_text.strip()
    if not text:
        raise ClassificationInputError("No text could be extracted from this document.")
    return text[:TEXT_BUDGET]


async def _known_hs_codes(session: AsyncSession) -> list[str]:
    """Distinct HS codes we already have rate data for (grounding hints)."""
    result = await session.execute(
        select(DutyTaxRate.hs_code)
        .where(DutyTaxRate.hs_code != GENERAL_HS_CODE, DutyTaxRate.status == "approved")
        .distinct()
        .order_by(DutyTaxRate.hs_code)
        .limit(50)
    )
    return list(result.scalars().all())


async def classify_hs_code(
    session: AsyncSession,
    *,
    text: str | None = None,
    library_document_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
) -> HsClassificationOut:
    """Classify a product description or document into candidate HS codes.

    Exactly one of `text` or `library_document_id` should be provided; if
    both are given, the document text wins. `owner_id` is required (and used
    to scope the lookup) whenever `library_document_id` is given.
    """
    if library_document_id is not None:
        if owner_id is None:
            raise ClassificationInputError(
                "owner_id is required when classifying from a library document."
            )
        resolved_text = await _load_document_text(session, library_document_id, owner_id)
    elif text is not None and text.strip():
        resolved_text = text.strip()[:TEXT_BUDGET]
    else:
        raise ClassificationInputError("Provide either 'text' or 'library_document_id'.")

    known_codes = await _known_hs_codes(session)
    client = get_llm_client()
    messages = build_hs_classify_messages(resolved_text, known_codes)

    try:
        parsed = await asyncio.to_thread(
            complete_json,
            client,
            messages,
            HS_CLASSIFY_SCHEMA,
            think=not settings.llm_disable_thinking_for_fast_calls,
            timeout=settings.llm_fast_timeout_seconds,
        )
    except SchemaEnforceError as exc:
        raise SchemaEnforceError(
            "HS code classification failed -- the model could not produce a "
            "valid response. Please try again."
        ) from exc

    if isinstance(parsed, list):
        parsed = {"candidates": parsed}

    candidates_raw = parsed.get("candidates") or []
    candidates = [
        HsCandidate(
            hs_code=str(c.get("hs_code", "")).strip(),
            description=c.get("description"),
            confidence=float(c.get("confidence", 0) or 0),
            reasoning=c.get("reasoning"),
        )
        for c in candidates_raw
        if isinstance(c, dict) and c.get("hs_code")
    ]
    return HsClassificationOut(
        product_summary=parsed.get("product_summary"),
        candidates=candidates,
    )
