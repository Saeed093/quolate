"""Global document library endpoints: upload, list, delete, link/unlink to projects."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, File, Query, UploadFile, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import get_owned_project
from app.auth.deps import get_current_user
from app.db.models import (
    LibraryDocument,
    LibraryDocumentComment,
    LibraryDocumentEmbedding,
    Project,
    ProjectLibraryDocument,
    User,
)
from app.db.session import get_session
from app.library.quota import library_quota_bytes, library_usage_bytes
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


class BulkDeleteRequest(BaseModel):
    ids: list[uuid.UUID] = Field(..., min_length=1)


async def _project_links_by_doc(
    session: AsyncSession, owner_id: uuid.UUID, doc_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[dict]]:
    if not doc_ids:
        return {}
    rows = (
        await session.execute(
            select(
                ProjectLibraryDocument.library_document_id,
                Project.id,
                Project.name,
            )
            .join(Project, Project.id == ProjectLibraryDocument.project_id)
            .where(
                Project.owner_id == owner_id,
                ProjectLibraryDocument.library_document_id.in_(doc_ids),
            )
            .order_by(Project.name)
        )
    ).all()
    out: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for lib_id, pid, pname in rows:
        out[lib_id].append({"id": str(pid), "name": pname})
    return out


async def _delete_library_document_record(
    session: AsyncSession, doc: LibraryDocument
) -> None:
    try:
        await asyncio.to_thread(storage.delete, doc.storage_key)
    except Exception as exc:
        log.warning("storage delete failed for %s: %s", doc.storage_key, exc)
    await session.delete(doc)


@router.get("/quota")
async def library_storage_quota(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Current library storage usage vs per-user quota."""
    used = await library_usage_bytes(session, user.id)
    count = (
        await session.execute(
            select(func.count()).select_from(LibraryDocument).where(
                LibraryDocument.owner_id == user.id
            )
        )
    ).scalar_one()
    limit = library_quota_bytes()
    return {
        "used_bytes": used,
        "limit_bytes": limit,
        "document_count": int(count or 0),
        "remaining_bytes": max(0, limit - used),
    }


@router.post("/documents")
async def upload_library_documents(
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Upload documents to the global library. Returns created/skipped document IDs."""
    from app.jobs import queue

    results = {"created": [], "skipped": [], "errors": []}
    quota_limit = library_quota_bytes()
    quota_label_mb = quota_limit // (1024 * 1024)

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
            file_size = len(content)
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

            used = await library_usage_bytes(session, user.id)
            if used + file_size > quota_limit:
                results["errors"].append(
                    {
                        "filename": file.filename,
                        "error": (
                            f"storage limit exceeded ({quota_label_mb} MB) — "
                            f"need {file_size} bytes, {max(0, quota_limit - used)} remaining"
                        ),
                    }
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
                size_bytes=file_size,
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
    sort: str = Query("newest", pattern="^(newest|oldest|name)$"),
    project_id: str | None = Query(
        None,
        description="Filter by project UUID, or 'unlinked' for docs not linked to any project",
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """List the current user's library documents (with comment counts and project links)."""
    comment_count = (
        select(
            LibraryDocumentComment.library_document_id,
            func.count(LibraryDocumentComment.id).label("n"),
        )
        .group_by(LibraryDocumentComment.library_document_id)
        .subquery()
    )
    query = (
        select(LibraryDocument, comment_count.c.n)
        .join(
            comment_count,
            comment_count.c.library_document_id == LibraryDocument.id,
            isouter=True,
        )
        .where(LibraryDocument.owner_id == user.id)
    )

    if project_id == "unlinked":
        linked_subq = (
            select(ProjectLibraryDocument.library_document_id)
            .join(Project, Project.id == ProjectLibraryDocument.project_id)
            .where(Project.owner_id == user.id)
        )
        query = query.where(LibraryDocument.id.not_in(linked_subq))
    elif project_id:
        try:
            pid = uuid.UUID(project_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid project_id",
            ) from exc
        await get_owned_project(pid, user, session)
        linked_for_project = select(ProjectLibraryDocument.library_document_id).where(
            ProjectLibraryDocument.project_id == pid
        )
        query = query.where(LibraryDocument.id.in_(linked_for_project))

    if sort == "oldest":
        query = query.order_by(LibraryDocument.created_at.asc())
    elif sort == "name":
        query = query.order_by(LibraryDocument.original_filename.asc())
    else:
        query = query.order_by(LibraryDocument.created_at.desc())

    rows = (await session.execute(query)).all()
    doc_ids = [doc.id for doc, _ in rows]
    links_by_doc = await _project_links_by_doc(session, user.id, doc_ids)

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
            "size_bytes": int(doc.size_bytes or 0),
            "projects": links_by_doc.get(doc.id, []),
        }
        for doc, n in rows
    ]


@router.post("/documents/bulk-delete")
async def bulk_delete_library_documents(
    body: BulkDeleteRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete multiple library documents in one request."""
    deleted: list[str] = []
    not_found: list[str] = []

    for doc_id in body.ids:
        doc = (
            await session.execute(
                select(LibraryDocument).where(
                    LibraryDocument.id == doc_id,
                    LibraryDocument.owner_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if doc is None:
            not_found.append(str(doc_id))
            continue
        await _delete_library_document_record(session, doc)
        deleted.append(str(doc_id))

    await session.commit()
    return {"deleted": deleted, "not_found": not_found, "count": len(deleted)}


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
    doc = await _get_owned_library_doc(doc_id, user, session)
    await _delete_library_document_record(session, doc)
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
