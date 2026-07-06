"""Stage 4-5: persist extracted fields, roll up quotes, embed for correlation."""
from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BomItem,
    Document,
    DocumentEmbedding,
    ExtractedField,
    Quote,
    Supplier,
)
from app.ingestion.provenance import locate_snippet
from app.ingestion.types import PageContent
from app.llm.embeddings import embed_text

LOW_CONFIDENCE = 0.7
_ROLLUP_TYPES = {"unit_price", "moq", "lead_time_days", "currency", "incoterms"}


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


async def _resolve_supplier(
    session: AsyncSession, document: Document, supplier_name: str | None
) -> Supplier:
    if document.supplier_id is not None:
        result = await session.execute(
            select(Supplier).where(Supplier.id == document.supplier_id)
        )
        supplier = result.scalar_one_or_none()
        if supplier is not None:
            return supplier

    name = (supplier_name or "").strip() or "Unknown Supplier"
    result = await session.execute(
        select(Supplier).where(
            Supplier.project_id == document.project_id, Supplier.name == name
        )
    )
    supplier = result.scalar_one_or_none()
    if supplier is None:
        supplier = Supplier(project_id=document.project_id, name=name)
        session.add(supplier)
        await session.flush()
    # Link the document to the resolved supplier.
    document.supplier_id = supplier.id
    return supplier


async def persist_extraction(
    session: AsyncSession,
    document: Document,
    extraction: dict,
    pages: list[PageContent],
) -> int:
    """Persist fields + quotes + embedding. Returns count of low-confidence fields."""
    # Map BOM line_no -> bom_item_id for this project.
    result = await session.execute(
        select(BomItem).where(BomItem.project_id == document.project_id)
    )
    line_to_item: dict[int, uuid.UUID] = {
        b.line_no: b.id for b in result.scalars().all()
    }

    supplier = await _resolve_supplier(
        session, document, extraction.get("supplier_name")
    )
    doc_currency = extraction.get("currency")

    needs_review = 0
    # Group rollup values per bom_item_id.
    rollup: dict[uuid.UUID | None, dict] = {}

    for f in extraction.get("fields", []) or []:
        field_type = f.get("field_type")
        if not field_type:
            continue
        line_no = f.get("bom_line_no")
        bom_item_id = line_to_item.get(line_no) if line_no is not None else None
        confidence = f.get("confidence")
        try:
            conf_val = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            conf_val = None
        value_num = _to_decimal(f.get("value_num"))
        provenance = locate_snippet(f.get("source_snippet"), pages)

        ef = ExtractedField(
            document_id=document.id,
            bom_item_id=bom_item_id,
            supplier_id=supplier.id,
            field_type=field_type,
            value_text=f.get("value_text"),
            value_num=value_num,
            unit=f.get("unit"),
            confidence=conf_val,
            status="auto",
            provenance=provenance,
        )
        session.add(ef)

        if conf_val is not None and conf_val < LOW_CONFIDENCE:
            needs_review += 1

        base_type = field_type.split(":", 1)[0]
        if base_type in _ROLLUP_TYPES:
            bucket = rollup.setdefault(bom_item_id, {})
            field_currency = f.get("currency") or doc_currency
            if base_type == "unit_price" and value_num is not None:
                bucket["unit_price"] = value_num
                if field_currency:
                    bucket.setdefault("currency", field_currency)
            elif base_type == "moq" and value_num is not None:
                bucket["moq"] = value_num
            elif base_type == "lead_time_days" and value_num is not None:
                bucket["lead_time_days"] = int(value_num)
            elif base_type == "currency" and (f.get("value_text") or field_currency):
                bucket["currency"] = f.get("value_text") or field_currency
            elif base_type == "incoterms":
                bucket["incoterms"] = f.get("value_text")

    await _rollup_quotes(session, document, supplier.id, rollup)
    await _embed_document(session, document, extraction, supplier.name, pages)

    return needs_review


async def _rollup_quotes(
    session: AsyncSession,
    document: Document,
    supplier_id: uuid.UUID,
    rollup: dict[uuid.UUID | None, dict],
) -> None:
    for bom_item_id, vals in rollup.items():
        if not any(k in vals for k in ("unit_price", "moq", "lead_time_days")):
            continue
        quote = Quote(
            project_id=document.project_id,
            supplier_id=supplier_id,
            document_id=document.id,
            bom_item_id=bom_item_id,
            unit_price=vals.get("unit_price"),
            currency=vals.get("currency"),
            moq=vals.get("moq"),
            lead_time_days=vals.get("lead_time_days"),
            incoterms=vals.get("incoterms"),
        )
        session.add(quote)
        await session.flush()

        # Supersede prior active quotes for same supplier + bom line.
        conditions = [
            Quote.project_id == document.project_id,
            Quote.supplier_id == supplier_id,
            Quote.id != quote.id,
            Quote.superseded_by.is_(None),
        ]
        if bom_item_id is None:
            conditions.append(Quote.bom_item_id.is_(None))
        else:
            conditions.append(Quote.bom_item_id == bom_item_id)
        await session.execute(
            update(Quote).where(*conditions).values(superseded_by=quote.id)
        )


async def _embed_document(
    session: AsyncSession,
    document: Document,
    extraction: dict,
    supplier_name: str,
    pages: list[PageContent] | None = None,
) -> None:
    # Idempotent re-parse (retries/requeues): clear previous rows first.
    from sqlalchemy import delete

    await session.execute(
        delete(DocumentEmbedding).where(DocumentEmbedding.document_id == document.id)
    )

    # Summary row (supplier + extracted fields) — powers quote-match correlation.
    parts: list[str] = [supplier_name]
    for f in extraction.get("fields", []) or []:
        snippet = f.get("value_text") or f.get("source_snippet")
        if snippet:
            parts.append(f"{f.get('field_type')}: {snippet}")
    content = "\n".join(p for p in parts if p).strip()
    if content:
        vector = embed_text(content)
        session.add(
            DocumentEmbedding(
                document_id=document.id,
                project_id=document.project_id,
                content=content,
                embedding=vector,
            )
        )

    # Full-text chunks — power general RAG search over the whole document.
    from app.ingestion.chunking import chunk_text

    full_text = "\n".join(p.text for p in (pages or []) if p.text)
    for chunk in chunk_text(full_text):
        if chunk.strip() == content:
            continue
        session.add(
            DocumentEmbedding(
                document_id=document.id,
                project_id=document.project_id,
                content=chunk,
                embedding=embed_text(chunk),
            )
        )
