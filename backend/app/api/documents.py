"""Documents router: upload (dedup + enqueue), list, review, page images."""
from __future__ import annotations

import hashlib
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import get_owned_document, get_owned_project
from app.auth.deps import get_current_user
from app.db.models import Document, DocumentEmbedding, ExtractedField, Quote, User
from app.db.session import get_session
from app.ingestion.rasterize import pdf_page_to_png
from app.jobs import queue
from app.schemas import DocumentOut, DocumentReview, ExtractedFieldOut
from app.storage import storage

router = APIRouter(tags=["documents"])

_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp"}


def _ext(filename: str) -> str:
    idx = filename.rfind(".")
    return filename[idx:].lower() if idx != -1 else ""


def _infer_kind(filename: str, mime: str | None, given: str | None) -> str:
    if given:
        return given
    ext = _ext(filename)
    if ext == ".zip":
        return "whatsapp_export"
    if ext in {".eml"}:
        return "email"
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
        return "screenshot"
    return "quote"


async def _reset_document_for_reparse(session: AsyncSession, document: Document) -> None:
    """Clear prior extraction rows so a re-parse starts clean."""
    doc_id = document.id
    await session.execute(delete(ExtractedField).where(ExtractedField.document_id == doc_id))
    await session.execute(delete(Quote).where(Quote.document_id == doc_id))
    await session.execute(
        delete(DocumentEmbedding).where(DocumentEmbedding.document_id == doc_id)
    )
    document.status = "pending"
    document.error = None
    document.page_count = None
    document.ocr_used = False
    document.stage_log = {}
    document.supplier_id = None


@router.post(
    "/projects/{project_id}/documents",
    response_model=list[DocumentOut],
    status_code=201,
)
async def upload_documents(
    project_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    kind: str | None = Form(default=None),
    supplier_id: uuid.UUID | None = Form(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Document]:
    await get_owned_project(project_id, user, session)

    created: list[Document] = []
    for upload in files:
        data = await upload.read()
        if not data:
            continue
        sha = hashlib.sha256(data).hexdigest()

        existing = await session.execute(
            select(Document).where(
                Document.project_id == project_id, Document.sha256 == sha
            )
        )
        dup = existing.scalar_one_or_none()
        if dup is not None:
            if dup.status == "failed":
                await _reset_document_for_reparse(session, dup)
                await queue.enqueue(
                    session, "parse_document", {"document_id": str(dup.id)}
                )
            created.append(dup)
            continue

        filename = upload.filename or f"upload{_ext(upload.filename or '')}"
        storage_key = f"projects/{project_id}/documents/{sha}{_ext(filename)}"
        await _save(storage_key, data, upload.content_type)

        doc = Document(
            project_id=project_id,
            supplier_id=supplier_id,
            kind=_infer_kind(filename, upload.content_type, kind),
            original_filename=filename,
            storage_key=storage_key,
            mime_type=upload.content_type,
            sha256=sha,
            status="pending",
        )
        session.add(doc)
        await session.flush()
        await queue.enqueue(session, "parse_document", {"document_id": str(doc.id)})
        created.append(doc)

    await session.commit()
    for doc in created:
        await session.refresh(doc)
    return created


async def _save(key: str, data: bytes, content_type: str | None) -> None:
    import asyncio

    await asyncio.to_thread(storage.save, key, data, content_type)


@router.get("/projects/{project_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Document]:
    await get_owned_project(project_id, user, session)
    result = await session.execute(
        select(Document)
        .where(Document.project_id == project_id)
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/documents/{document_id}/review", response_model=DocumentReview)
async def review_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DocumentReview:
    document = await get_owned_document(document_id, user, session)
    result = await session.execute(
        select(ExtractedField)
        .where(ExtractedField.document_id == document_id)
        .order_by(ExtractedField.confidence)
    )
    fields = list(result.scalars().all())
    page_urls = [
        f"/documents/{document_id}/pages/{n}.png"
        for n in range(1, (document.page_count or 0) + 1)
    ]
    return DocumentReview(
        document=DocumentOut.model_validate(document),
        fields=[ExtractedFieldOut.model_validate(f) for f in fields],
        page_urls=page_urls,
    )


@router.post("/documents/{document_id}/mark-reviewed", response_model=DocumentOut)
async def mark_reviewed(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Document:
    """Promote a needs_review (or failed) document to parsed once the user is satisfied.

    Idempotent: calling it on an already-parsed document returns 200 without error.
    """
    document = await get_owned_document(document_id, user, session)
    if document.status in ("parsed",):
        # Already done — idempotent success.
        return document
    if document.status in ("pending", "processing"):
        raise HTTPException(
            status_code=409,
            detail=f"Document is currently being processed (status: {document.status})",
        )
    document.status = "parsed"
    document.error = None
    await session.commit()
    await session.refresh(document)
    return document


@router.post("/documents/{document_id}/reparse", response_model=DocumentOut)
async def reparse_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Document:
    document = await get_owned_document(document_id, user, session)
    if document.status in ("pending", "processing"):
        raise HTTPException(status_code=409, detail="Document is already being processed")
    await _reset_document_for_reparse(session, document)
    await queue.enqueue(session, "parse_document", {"document_id": str(document.id)})
    await session.commit()
    await session.refresh(document)
    return document


@router.get("/documents/{document_id}/pages/{page_no}.png")
async def get_page_image(
    document_id: uuid.UUID,
    page_no: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    import asyncio

    document = await get_owned_document(document_id, user, session)
    cache_key = f"projects/{document.project_id}/documents/{document.sha256}/pages/{page_no}.png"

    if await asyncio.to_thread(storage.exists, cache_key):
        png = await asyncio.to_thread(storage.get, cache_key)
        return Response(content=png, media_type="image/png")

    data = await asyncio.to_thread(storage.get, document.storage_key)
    mime = (document.mime_type or "").lower()
    if _ext(document.original_filename) == ".pdf" or "pdf" in mime:
        try:
            png = await asyncio.to_thread(pdf_page_to_png, data, page_no - 1)
        except Exception:
            raise HTTPException(status_code=404, detail="Page not found")
    elif mime in _IMAGE_MIMES or _ext(document.original_filename) in {
        ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif",
    }:
        if page_no != 1:
            raise HTTPException(status_code=404, detail="Page not found")
        png = data
    else:
        raise HTTPException(status_code=404, detail="No page image available")

    await asyncio.to_thread(storage.save, cache_key, png, "image/png")
    return Response(content=png, media_type="image/png")


@router.get("/documents/{document_id}/original")
async def get_original(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    import asyncio

    document = await get_owned_document(document_id, user, session)
    data = await asyncio.to_thread(storage.get, document.storage_key)
    return Response(
        content=data,
        media_type=document.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{document.original_filename}"'
        },
    )
