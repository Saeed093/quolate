"""index_tender job: full-text RAG indexing for a tender.

Runs in the background worker after a pull upserts a tender:
  1. Chunk-embeds the tender's detail-page text into tender_embeddings.
  2. Downloads tender documents (PDF attachments) linked from the detail page,
     stores them, extracts text (OCR if scanned) and chunk-embeds that too.

Fails soft everywhere — a tender with no detail page or unreachable documents
still gets its raw_text indexed.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from urllib.parse import urljoin, urlparse

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Tender, TenderDocument, TenderEmbedding
from app.ingestion.chunking import chunk_text
from app.jobs.registry import register
from app.llm.embeddings import embed_texts
from app.storage import storage

log = logging.getLogger("quolate.tenders.indexer")

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024  # 20 MB cap per attachment
MAX_DOCUMENTS_PER_TENDER = 5

# Anchor text that indicates a downloadable tender document.
_DOC_LINK_RE = re.compile(
    r"download|tender\s*document|advertisement|bidding|attachment", re.IGNORECASE
)


def _find_document_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Return [(absolute_url, label)] for document-looking links on a detail page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        label = a.get_text(" ", strip=True) or a.get("title") or ""
        blob = f"{label} {href}"
        if not _DOC_LINK_RE.search(blob):
            continue
        # Skip navigation/self links.
        if href.startswith(("#", "javascript:", "mailto:")):
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        links.append((url, label or "document"))
    return links[:MAX_DOCUMENTS_PER_TENDER]


def _fetch_bytes(url: str) -> tuple[bytes, str | None, str]:
    """Download a URL. Returns (data, content_type, filename)."""
    import httpx

    headers = {"User-Agent": settings.scrape_user_agent}
    with httpx.Client(timeout=60, follow_redirects=True, headers=headers) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "").split(";")[0].strip()
            # Filename from content-disposition or URL path.
            cd = resp.headers.get("content-disposition", "")
            m = re.search(r'filename="?([^";]+)"?', cd)
            filename = m.group(1) if m else (urlparse(url).path.rsplit("/", 1)[-1] or "document")
            data = b""
            for chunk in resp.iter_bytes():
                data += chunk
                if len(data) > MAX_DOCUMENT_BYTES:
                    raise ValueError(f"document exceeds {MAX_DOCUMENT_BYTES} bytes")
    return data, content_type or None, filename


def _fetch_text(url: str) -> str:
    import httpx

    headers = {"User-Agent": settings.scrape_user_agent}
    with httpx.Client(timeout=30, follow_redirects=True, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text


async def _embed_chunks(
    session: AsyncSession,
    tender_id: uuid.UUID,
    text: str,
    *,
    tender_document_id: uuid.UUID | None,
) -> int:
    chunks = chunk_text(text)
    if not chunks:
        return 0
    vectors = await asyncio.to_thread(embed_texts, chunks)
    for chunk, vector in zip(chunks, vectors):
        session.add(
            TenderEmbedding(
                tender_id=tender_id,
                tender_document_id=tender_document_id,
                content=chunk,
                embedding=vector,
            )
        )
    return len(chunks)


@register("index_tender")
async def index_tender(session: AsyncSession, payload: dict) -> None:
    tender_id = uuid.UUID(payload["tender_id"])
    tender = (
        await session.execute(select(Tender).where(Tender.id == tender_id))
    ).scalar_one_or_none()
    if tender is None:
        return

    # Snapshot scalars before commit() expires the ORM instance (async session).
    tender_no = tender.tender_no
    detail_url = tender.detail_url

    # Idempotent re-index: clear previous chunks.
    await session.execute(
        delete(TenderEmbedding).where(TenderEmbedding.tender_id == tender_id)
    )

    # 1. Detail-page / notice text.
    header = "\n".join(
        p for p in [tender.title, tender.organization, tender_no] if p
    )
    body = tender.raw_text or ""
    try:
        n = await _embed_chunks(
            session, tender_id, f"{header}\n{body}".strip(), tender_document_id=None
        )
        log.info("indexed tender %s text: %d chunks", tender_no, n)
    except Exception:
        log.warning("tender %s text indexing failed", tender_no, exc_info=True)
    await session.commit()

    # 2. Tender documents from the detail page (best-effort).
    if not detail_url:
        return
    try:
        html = await asyncio.to_thread(_fetch_text, detail_url)
        links = _find_document_links(html, detail_url)
    except Exception:
        log.warning(
            "tender %s detail page fetch failed", tender_no, exc_info=True
        )
        return

    for url, label in links:
        try:
            data, content_type, filename = await asyncio.to_thread(_fetch_bytes, url)
            if not data:
                continue
            # Only index document-like content; skip HTML pages.
            if content_type and "html" in content_type:
                continue
            sha = hashlib.sha256(data).hexdigest()
            existing = (
                await session.execute(
                    select(TenderDocument).where(
                        TenderDocument.tender_id == tender_id,
                        TenderDocument.sha256 == sha,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue

            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            storage_key = f"tenders/{tender_id}/documents/{sha}{ext}"
            await asyncio.to_thread(storage.save, storage_key, data, content_type)

            doc = TenderDocument(
                tender_id=tender_id,
                filename=filename,
                storage_key=storage_key,
                sha256=sha,
                mime_type=content_type,
                status="processing",
            )
            session.add(doc)
            await session.flush()

            from app.ingestion.extract import extract_content

            content = await asyncio.to_thread(
                extract_content, filename, content_type, data
            )
            n = await _embed_chunks(
                session, tender_id, content.full_text, tender_document_id=doc.id
            )
            doc.status = "parsed"
            doc.error = None
            log.info(
                "indexed tender %s document %s (%s): %d chunks",
                tender_no,
                filename,
                label,
                n,
            )
            await session.commit()
        except Exception as exc:
            log.warning(
                "tender %s document %s failed: %r", tender_no, url, exc
            )
            try:
                await session.rollback()
            except Exception:
                pass
