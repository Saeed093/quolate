"""Global document library endpoints: upload, list, delete, link/unlink to projects."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import get_owned_project
from app.auth.deps import get_current_user
from app.db.models import (
    LibraryDocument,
    LibraryDocumentComment,
    LibraryDocumentEmbedding,
    ProjectLibraryDocument,
    User,
)
from app.db.session import get_session
from app.storage import storage

log = logging.getLogger("quolate.api.library")

router = APIRouter(prefix="/library", tags=["library"])

# File types the extraction pipeline can actually read.
SUPPORTED_EXTENSIONS = {
    "pdf", "png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff", "gif",
    "xlsx", "xlsm", "xls", "csv", "txt", "eml", "zip", "docx", "pptx",
}


def _infer_kind(filename: str, mime_type: str | None = None) -> str:
    """Infer document kind from extension and mime type."""
    ext = (filename.split(".")[-1] if "." in filename else "").lower()
    mime_lower = (mime_type or "").lower()

    if ext in ("pdf",):
        return "pdf"
    if ext in ("png", "jpg", "jpeg", "gif", "webp"):
        return "photo"
    if ext in ("doc", "docx"):
        return "correspondence"
    if ext in ("xls", "xlsx", "csv"):
        return "past_quote"
    if "image" in mime_lower:
        return "photo"
    if "pdf" in mime_lower:
        return "pdf"
    return "other"


@router.post("/documents")
async def upload_library_documents(
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Upload documents to the global library. Returns created/skipped document IDs."""
    from app.jobs import queue

    results = {"created": [], "skipped": [], "errors": []}

    for file in files:
        if not file.filename:
            results["errors"].append({"error": "missing filename"})
            continue

        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in SUPPORTED_EXTENSIONS:
            results["errors"].append(
                {
                    "filename": file.filename,
                    "error": f"unsupported file type '.{ext or '?'}' — supported: "
                    "pdf, images, docx, pptx, xlsx, csv, txt, eml, zip",
                }
            )
            continue

        try:
            content = await file.read()
            sha256_hash = hashlib.sha256(content).hexdigest()

            # Check for dedup by (owner, sha256).
            existing = (
                await session.execute(
                    select(LibraryDocument).where(
                        LibraryDocument.owner_id == user.id,
                        LibraryDocument.sha256 == sha256_hash,
                    )
                )
            ).scalar_one_or_none()

            if existing is not None:
                results["skipped"].append(
                    {"filename": file.filename, "id": str(existing.id), "reason": "duplicate"}
                )
                continue

            kind = _infer_kind(file.filename, file.content_type)
            ext = f".{file.filename.split('.')[-1]}" if '.' in file.filename else ""
            storage_key = f"library/{user.id}/documents/{sha256_hash}{ext}"

            # Save to storage (sync call in thread).
            await asyncio.to_thread(storage.save, storage_key, content, file.content_type)

            # Create document row.
            doc = LibraryDocument(
                owner_id=user.id,
                kind=kind,
                original_filename=file.filename,
                storage_key=storage_key,
                mime_type=file.content_type,
                sha256=sha256_hash,
                status="pending",
            )
            session.add(doc)
            await session.flush()

            # Enqueue parse job.
            await queue.enqueue(
                session, "parse_library_document", {"library_document_id": str(doc.id)}
            )
            await session.commit()

            results["created"].append(
                {"id": str(doc.id), "filename": file.filename, "kind": kind}
            )
        except Exception as exc:
            log.exception("upload failed for %s", file.filename)
            results["errors"].append({"filename": file.filename, "error": str(exc)[:200]})

    return results


@router.get("/documents")
async def list_library_documents(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """List the current user's library documents (with comment counts)."""
    from sqlalchemy import func

    comment_count = (
        select(
            LibraryDocumentComment.library_document_id,
            func.count(LibraryDocumentComment.id).label("n"),
        )
        .group_by(LibraryDocumentComment.library_document_id)
        .subquery()
    )
    result = await session.execute(
        select(LibraryDocument, comment_count.c.n)
        .join(
            comment_count,
            comment_count.c.library_document_id == LibraryDocument.id,
            isouter=True,
        )
        .where(LibraryDocument.owner_id == user.id)
        .order_by(LibraryDocument.created_at.desc())
    )
    return [
        {
            "id": str(doc.id),
            "filename": doc.original_filename,
            "kind": doc.kind,
            "status": doc.status,
            "page_count": doc.page_count,
            "error": doc.error,
            "comment_count": int(n or 0),
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        }
        for doc, n in result.all()
    ]


async def _get_owned_library_doc(
    doc_id: uuid.UUID, user: User, session: AsyncSession
) -> LibraryDocument:
    doc = (
        await session.execute(
            select(LibraryDocument).where(
                LibraryDocument.id == doc_id,
                LibraryDocument.owner_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    return doc


# ---- Comments ----
@router.get("/documents/{doc_id}/comments")
async def list_document_comments(
    doc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    await _get_owned_library_doc(doc_id, user, session)
    rows = (
        await session.execute(
            select(LibraryDocumentComment)
            .where(LibraryDocumentComment.library_document_id == doc_id)
            .order_by(LibraryDocumentComment.created_at)
        )
    ).scalars().all()
    return [
        {
            "id": str(c.id),
            "content": c.content,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in rows
    ]


@router.post("/documents/{doc_id}/comments")
async def add_document_comment(
    doc_id: uuid.UUID,
    body: dict,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.config import settings
    from app.llm.embeddings import embed_text

    await _get_owned_library_doc(doc_id, user, session)
    content = str(body.get("content") or "").strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty comment"
        )

    embedding = None
    try:
        embedding = await asyncio.wait_for(
            asyncio.to_thread(embed_text, content[:8000]),
            timeout=settings.llm_fast_timeout_seconds,
        )
    except Exception:
        log.warning("comment embedding failed; saved without", exc_info=True)

    comment = LibraryDocumentComment(
        library_document_id=doc_id,
        owner_id=user.id,
        content=content,
        embedding=embedding,
    )
    session.add(comment)
    await session.commit()
    return {
        "id": str(comment.id),
        "content": comment.content,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
    }


@router.delete("/documents/{doc_id}/comments/{comment_id}")
async def delete_document_comment(
    doc_id: uuid.UUID,
    comment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _get_owned_library_doc(doc_id, user, session)
    comment = (
        await session.execute(
            select(LibraryDocumentComment).where(
                LibraryDocumentComment.id == comment_id,
                LibraryDocumentComment.library_document_id == doc_id,
            )
        )
    ).scalar_one_or_none()
    if comment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found"
        )
    await session.delete(comment)
    await session.commit()
    return {"deleted": str(comment_id)}


@router.delete("/documents/{doc_id}")
async def delete_library_document(
    doc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete a library document and its embeddings."""
    doc = (
        await session.execute(
            select(LibraryDocument).where(
                LibraryDocument.id == doc_id,
                LibraryDocument.owner_id == user.id,
            )
        )
    ).scalar_one_or_none()

    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Delete from storage.
    try:
        await asyncio.to_thread(storage.delete, doc.storage_key)
    except Exception as exc:
        log.warning("storage delete failed for %s: %s", doc.storage_key, exc)

    # Delete document (cascades to embeddings and project links via FK).
    await session.delete(doc)
    await session.commit()

    return {"deleted": str(doc_id)}


@router.get("/documents/{doc_id}/original")
async def get_library_document_original(
    doc_id: uuid.UUID,
    inline: bool = False,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Retrieve the original file. ?inline=1 renders in-browser instead of downloading."""
    from fastapi.responses import Response

    doc = await _get_owned_library_doc(doc_id, user, session)

    # Read file from storage.
    data = await asyncio.to_thread(storage.get, doc.storage_key)
    disposition = "inline" if inline else "attachment"
    return Response(
        content=data,
        media_type=doc.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'{disposition}; filename="{doc.original_filename}"'
        },
    )
