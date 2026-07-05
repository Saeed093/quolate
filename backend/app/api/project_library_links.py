"""Link/unlink library documents to projects."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import get_owned_project
from app.auth.deps import get_current_user
from app.db.models import LibraryDocument, Project, ProjectLibraryDocument, User
from app.db.session import get_session

router = APIRouter(prefix="/projects", tags=["project-library"])


@router.get("/{project_id}/library-documents")
async def list_project_library_documents(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """List library documents linked to a project."""
    project = await get_owned_project(project_id, user, session)

    result = await session.execute(
        select(ProjectLibraryDocument, LibraryDocument)
        .join(
            LibraryDocument,
            ProjectLibraryDocument.library_document_id == LibraryDocument.id,
        )
        .where(ProjectLibraryDocument.project_id == project.id)
        .order_by(ProjectLibraryDocument.created_at.desc())
    )
    rows = result.all()

    return [
        {
            "id": str(link.id),
            "library_document_id": str(lib_doc.id),
            "filename": lib_doc.original_filename,
            "kind": lib_doc.kind,
            "status": lib_doc.status,
            "linked_at": link.created_at.isoformat() if link.created_at else None,
        }
        for link, lib_doc in rows
    ]


@router.post("/{project_id}/library-documents")
async def link_library_document(
    project_id: uuid.UUID,
    body: dict,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Link a library document to a project (idempotent)."""
    project = await get_owned_project(project_id, user, session)
    library_document_id = body.get("library_document_id")

    if not library_document_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing library_document_id")

    # Verify the library document belongs to the user.
    lib_doc = (
        await session.execute(
            select(LibraryDocument).where(
                LibraryDocument.id == uuid.UUID(str(library_document_id)),
                LibraryDocument.owner_id == user.id,
            )
        )
    ).scalar_one_or_none()

    if lib_doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Library document not found"
        )

    # Create link (unique constraint on project_id + library_document_id).
    try:
        link = ProjectLibraryDocument(
            project_id=project.id, library_document_id=lib_doc.id
        )
        session.add(link)
        await session.commit()
        return {"id": str(link.id), "linked": True}
    except IntegrityError:
        await session.rollback()
        # Already linked — return idempotent success.
        return {"linked": True, "already_existed": True}


@router.delete("/{project_id}/library-documents/{link_id}")
async def unlink_library_document(
    project_id: uuid.UUID,
    link_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Unlink a library document from a project."""
    project = await get_owned_project(project_id, user, session)

    link = (
        await session.execute(
            select(ProjectLibraryDocument).where(
                ProjectLibraryDocument.id == link_id,
                ProjectLibraryDocument.project_id == project.id,
            )
        )
    ).scalar_one_or_none()

    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")

    await session.delete(link)
    await session.commit()

    return {"deleted": True}
