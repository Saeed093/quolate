"""Pull orchestration: list -> fetch -> classify -> embed -> upsert.

Fails soft per source (never crashes the worker), polite request spacing, and
individually re-runnable. Adapters do the site-specific parsing.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tender, TenderSource
from app.llm.embeddings import embed_text
from app.tenders.adapters import NoticeData, get_adapter
from app.tenders.classifier import classify_tender
from app.tenders.vocab import normalize_org_type

log = logging.getLogger("quolate.tenders")

POLITE_DELAY_SECONDS = 2.0


def _embed_content(data: NoticeData) -> str:
    parts = [data.title or "", *data.items, data.organization or ""]
    return "\n".join(p for p in parts if p).strip()


async def upsert_notice(
    session: AsyncSession,
    source: TenderSource,
    data: NoticeData,
    *,
    adapter_org_default: str = "other",
) -> tuple[str, Tender]:
    """Insert or update a tender; link corrigenda. Returns (action, tender)."""
    from app.config import settings
    from app.tenders.vocab import category_from_label, normalize_sector_tags

    adapter_category = category_from_label(data.category)
    if adapter_category:
        # The portal already provides a category label — no LLM call needed.
        cls = {
            "org_type": "other",
            "category": adapter_category,
            "sector_tags": normalize_sector_tags((data.category or "").split()),
        }
    else:
        try:
            cls = await asyncio.wait_for(
                asyncio.to_thread(
                    classify_tender, data.title, data.raw_text, data.organization
                ),
                timeout=settings.llm_fast_timeout_seconds,
            )
        except asyncio.TimeoutError:
            log.warning(
                "classify_tender timed out for %s, using fallback",
                data.tender_no or data.title or "unknown",
            )
            cls = {"org_type": "other", "category": None, "sector_tags": []}

    org_type = cls["org_type"]
    if org_type == "other" and adapter_org_default != "other":
        org_type = normalize_org_type(adapter_org_default)

    content = _embed_content(data)
    try:
        embedding = (
            (await asyncio.wait_for(
                asyncio.to_thread(embed_text, content),
                timeout=settings.llm_fast_timeout_seconds,
            ))
            if content
            else None
        )
    except asyncio.TimeoutError:
        log.warning(
            "embed_text timed out for %s, continuing without embedding",
            data.tender_no or data.title or "unknown",
        )
        embedding = None

    existing = None
    if data.tender_no:
        existing = (
            await session.execute(
                select(Tender).where(
                    Tender.source_id == source.id,
                    Tender.tender_no == data.tender_no,
                )
            )
        ).scalar_one_or_none()

    if existing is not None:
        tender = existing
        action = "updated"
    else:
        tender = Tender(source_id=source.id, tender_no=data.tender_no)
        session.add(tender)
        action = "created"

    old_raw_text = existing.raw_text if existing is not None else None

    tender.title = data.title
    tender.organization = data.organization
    tender.org_type = org_type
    tender.category = cls["category"]
    tender.sector_tags = cls["sector_tags"]
    tender.city = data.city
    tender.closing_date = data.closing_date
    tender.advertise_date = data.advertise_date
    tender.estimated_value = data.estimated_value
    tender.detail_url = data.detail_url or tender.detail_url
    tender.raw_text = data.raw_text
    tender.embedding = embedding
    await session.flush()

    # Queue background full-text indexing (detail text + tender documents)
    # only when there is new content, to avoid re-index churn on daily pulls.
    if action == "created" or (data.raw_text or "") != (old_raw_text or ""):
        from app.jobs import queue

        await queue.enqueue(session, "index_tender", {"tender_id": str(tender.id)})

    # Link corrigendum to the original tender (distinct tender_no).
    if data.corrigendum_of_tender_no:
        original = (
            await session.execute(
                select(Tender).where(
                    Tender.source_id == source.id,
                    Tender.tender_no == data.corrigendum_of_tender_no,
                )
            )
        ).scalar_one_or_none()
        if original is not None and original.id != tender.id:
            tender.corrigendum_of = original.id
            await session.flush()

    return action, tender


async def pull_source(
    session: AsyncSession,
    source: TenderSource,
    *,
    adapter=None,
    delay: float = POLITE_DELAY_SECONDS,
    max_notices: int | None = None,
    now: datetime | None = None,
    on_progress: Callable[[dict], None] | None = None,
) -> dict:
    """Run one source end-to-end. Never raises; records last_status.

    If *on_progress* is supplied it is called with progress dicts:
      {"phase":"listing"}, {"phase":"notice","index":i,"total":N,"title":...,"action":...}, {"phase":"done",...}
    """
    now = now or datetime.now(timezone.utc)
    adapter = adapter or get_adapter(source.adapter, source.base_url)
    adapter_org_default = getattr(adapter, "default_org_type", "other")

    def _emit(payload: dict) -> None:
        if on_progress:
            on_progress(payload)

    _emit({"phase": "listing", "source_name": source.name})

    try:
        refs = await asyncio.to_thread(adapter.list_notices)
    except Exception as exc:  # fail soft: mark source, don't crash
        log.warning("source %s listing failed: %r", source.id, exc)
        try:
            await session.refresh(source)
            source.last_status = "failed"
            source.last_run = now
            await session.flush()
        except Exception as flush_exc:
            log.warning("source %s status update failed: %r", source.id, flush_exc)
        result = {"status": "failed", "error": repr(exc), "created": 0, "updated": 0}
        _emit({"phase": "done", **result})
        return result

    created = updated = skipped = 0
    skipped_existing = 0
    if max_notices is not None:
        refs = refs[:max_notices]

    # New-only pulls: notices whose tender_no already exists are not
    # re-fetched/re-processed — only their dates are refreshed from the
    # listing row itself (cheap, no network / LLM / embedding work).
    existing_by_no: dict[str, Tender] = {}
    existing_rows = (
        await session.execute(
            select(Tender).where(
                Tender.source_id == source.id, Tender.tender_no.is_not(None)
            )
        )
    ).scalars().all()
    for t in existing_rows:
        existing_by_no[t.tender_no] = t

    total = len(refs)
    _emit({"phase": "fetching", "total": total, "source_name": source.name})

    for i, ref in enumerate(refs):
        title = getattr(ref, "title", None) or getattr(ref, "tender_no", None) or f"#{i+1}"

        existing = existing_by_no.get(ref.tender_no) if ref.tender_no else None
        if existing is not None:
            # Cheap refresh of dates from the listing row; skip everything else.
            from app.tenders.adapters.base import parse_date

            raw = ref.raw or {}
            changed = False
            new_closing = parse_date(raw.get("closing_date"))
            new_advertise = parse_date(raw.get("advertise_date"))
            if new_closing and new_closing != existing.closing_date:
                existing.closing_date = new_closing
                changed = True
            if new_advertise and new_advertise != existing.advertise_date:
                existing.advertise_date = new_advertise
                changed = True
            if changed:
                await session.flush()
            skipped_existing += 1
            _emit({
                "phase": "notice",
                "index": i,
                "total": total,
                "title": str(title),
                "step": "done",
                "action": "refreshed" if changed else "skipped",
            })
            continue

        _emit({
            "phase": "notice",
            "index": i,
            "total": total,
            "title": str(title),
            "step": "fetching",
        })
        try:
            data = await asyncio.to_thread(adapter.fetch_notice, ref)
            data = await _maybe_ocr_attachment(data)
            _emit({
                "phase": "notice",
                "index": i,
                "total": total,
                "title": data.title or str(title),
                "step": "classifying",
            })
            action, _ = await upsert_notice(
                session, source, data, adapter_org_default=adapter_org_default
            )
            if action == "created":
                created += 1
            else:
                updated += 1
            _emit({
                "phase": "notice",
                "index": i,
                "total": total,
                "title": data.title or str(title),
                "step": "done",
                "action": action,
            })
        except Exception as exc:  # skip a bad notice, keep going
            log.warning("notice parse failed for source %s: %r", source.id, exc)
            skipped += 1
            _emit({
                "phase": "notice",
                "index": i,
                "total": total,
                "title": str(title),
                "step": "error",
                "error": str(exc)[:200],
            })
        if delay and i < len(refs) - 1:
            await asyncio.sleep(delay)

    try:
        await session.refresh(source)
        source.last_status = "ok"
        source.last_run = now
        await session.flush()
    except Exception as exc:
        log.warning("source %s status update failed: %r", source.id, exc)
    result = {
        "status": "ok",
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "skipped_existing": skipped_existing,
        "total": total,
    }
    _emit({"phase": "done", **result})
    return result


async def _maybe_ocr_attachment(data: NoticeData) -> NoticeData:
    """Route a scanned attachment through the ingestion OCR pipeline (stages 1-2)."""
    if not data.attachment_bytes:
        return data
    try:
        from app.ingestion.extract import extract_content

        content = await asyncio.to_thread(
            extract_content,
            data.attachment_name or "notice.pdf",
            None,
            data.attachment_bytes,
        )
        if content.full_text.strip():
            data.raw_text = (data.raw_text + "\n" + content.full_text).strip()
    except Exception as exc:
        log.warning("attachment OCR failed: %r", exc)
    return data
