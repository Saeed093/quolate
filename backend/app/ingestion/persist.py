"""Stage 4-5: persist extracted fields, roll up quotes, embed for correlation."""
from __future__ import annotations

import re
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
from app.ingestion.bom_bootstrap import bootstrap_bom_from_extraction
from app.ingestion.provenance import locate_snippet
from app.ingestion.types import PageContent
from app.llm.embeddings import embed_text

LOW_CONFIDENCE = 0.7
_ROLLUP_TYPES = {"unit_price", "moq", "lead_time_days", "currency", "incoterms"}
# Field types where a fuzzy part-name match to a BOM line makes sense. Terms
# like incoterms/payment_terms are quotation-wide when bom_line_no is null —
# fuzzy-matching their snippet onto a line would mis-bucket them.
_FUZZY_MATCH_TYPES = {"unit_price", "moq", "spec"}
_NUM_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _parse_number_from_text(text: str | None) -> Decimal | None:
    """Pull the first numeric token out of a free-text price/qty string."""
    if not text:
        return None
    m = _NUM_RE.search(str(text).replace(" ", ""))
    if not m:
        return None
    return _to_decimal(m.group(0))


def _normalize_name(name: str | None) -> str:
    if not name:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _match_bom_by_name(
    part_name: str | None,
    bom_names: dict[uuid.UUID, str],
) -> uuid.UUID | None:
    """Best-effort fuzzy match of a quotation part name to an existing BOM row."""
    needle = _normalize_name(part_name)
    if not needle or not bom_names:
        return None
    # Exact normalized match first.
    for bom_id, name in bom_names.items():
        if _normalize_name(name) == needle:
            return bom_id
    # Substring / token overlap (prefer longest overlap).
    best_id: uuid.UUID | None = None
    best_score = 0
    needle_tokens = set(needle.split())
    for bom_id, name in bom_names.items():
        hay = _normalize_name(name)
        if not hay:
            continue
        if needle in hay or hay in needle:
            score = min(len(needle), len(hay))
            if score > best_score:
                best_score = score
                best_id = bom_id
            continue
        hay_tokens = set(hay.split())
        overlap = len(needle_tokens & hay_tokens)
        if overlap >= 2 and overlap > best_score:
            best_score = overlap
            best_id = bom_id
    return best_id


def _synthesize_fields_from_line_items(
    extraction: dict,
    line_to_item: dict[int, uuid.UUID],
    bom_names: dict[uuid.UUID, str],
) -> list[dict]:
    """When the LLM puts prices only in line_items, invent matching unit_price fields.

    Models often fill line_items.unit_price but omit fields[].unit_price — without
    this bridge the matrix stays empty even though the quote was parsed.
    """
    existing = extraction.get("fields") or []
    priced_bom_ids: set[uuid.UUID | None] = set()
    for f in existing:
        if (f.get("field_type") or "").split(":", 1)[0] != "unit_price":
            continue
        if f.get("value_num") is None and not _parse_number_from_text(f.get("value_text")):
            continue
        line_no = f.get("bom_line_no")
        if line_no is not None and line_no in line_to_item:
            priced_bom_ids.add(line_to_item[line_no])
        elif f.get("bom_item_id"):
            priced_bom_ids.add(f["bom_item_id"])

    synthesized: list[dict] = []
    doc_currency = extraction.get("currency")
    for item in extraction.get("line_items") or []:
        if not isinstance(item, dict):
            continue
        price = _to_decimal(item.get("unit_price"))
        if price is None:
            continue
        line_no = item.get("line_no")
        bom_item_id: uuid.UUID | None = None
        if line_no is not None:
            try:
                bom_item_id = line_to_item.get(int(line_no))
            except (TypeError, ValueError):
                bom_item_id = None
        if bom_item_id is None:
            bom_item_id = _match_bom_by_name(item.get("part_name"), bom_names)
        if bom_item_id is None or bom_item_id in priced_bom_ids:
            continue
        # Reverse-lookup line_no for the field record.
        mapped_line = next(
            (ln for ln, bid in line_to_item.items() if bid == bom_item_id),
            line_no,
        )
        synthesized.append(
            {
                "bom_line_no": mapped_line,
                "field_type": "unit_price",
                "value_num": float(price),
                "value_text": str(price),
                "currency": doc_currency,
                "confidence": 0.85,
                "source_snippet": item.get("part_name") or item.get("notes"),
            }
        )
        priced_bom_ids.add(bom_item_id)
    return synthesized


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
) -> tuple[int, int]:
    """Persist fields + quotes + embedding.

    Returns (count of low-confidence fields, count of auto-created BOM lines).
    """
    line_to_item, bom_created = await bootstrap_bom_from_extraction(
        session, document.project_id, extraction
    )

    # Load BOM names for fuzzy matching when bom_line_no is missing/wrong.
    bom_result = await session.execute(
        select(BomItem).where(BomItem.project_id == document.project_id)
    )
    bom_names = {b.id: b.part_name for b in bom_result.scalars().all()}

    # Bridge line_items.unit_price → fields when the model skipped fields.
    extra = _synthesize_fields_from_line_items(extraction, line_to_item, bom_names)
    if extra:
        fields = list(extraction.get("fields") or [])
        fields.extend(extra)
        extraction = {**extraction, "fields": fields}

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
        # Fuzzy fallback: match source_snippet / value_text to a BOM part name.
        # Only for per-line field types — document-level terms stay unmatched.
        if bom_item_id is None and field_type.split(":", 1)[0] in _FUZZY_MATCH_TYPES:
            bom_item_id = _match_bom_by_name(
                f.get("source_snippet") or f.get("value_text"), bom_names
            )
        confidence = f.get("confidence")
        try:
            conf_val = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            conf_val = None
        value_num = _to_decimal(f.get("value_num"))
        if value_num is None:
            value_num = _parse_number_from_text(f.get("value_text"))
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

    return needs_review, bom_created


async def _rollup_quotes(
    session: AsyncSession,
    document: Document,
    supplier_id: uuid.UUID,
    rollup: dict[uuid.UUID | None, dict],
) -> None:
    for bom_item_id, vals in rollup.items():
        if not any(
            k in vals for k in ("unit_price", "moq", "lead_time_days", "incoterms")
        ):
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
