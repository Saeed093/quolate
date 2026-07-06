"""Background activity summary for the global status popup."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.models import Document, Job, LibraryDocument, Project, TenderSource, User
from app.db.session import get_session
from app.schemas import ActivityOut, TenderPullActivity

router = APIRouter(tags=["activity"])

_BUSY_DOC_STATUSES = ("pending", "processing")
_PULL_JOB_STATUSES = ("queued", "running")


@router.get("/activity", response_model=ActivityOut)
async def get_activity(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ActivityOut:
    lib_count = (
        await session.execute(
            select(func.count())
            .select_from(LibraryDocument)
            .where(
                LibraryDocument.owner_id == user.id,
                LibraryDocument.status.in_(_BUSY_DOC_STATUSES),
            )
        )
    ).scalar_one()

    proj_count = (
        await session.execute(
            select(func.count())
            .select_from(Document)
            .join(Project, Document.project_id == Project.id)
            .where(
                Project.owner_id == user.id,
                Document.status.in_(_BUSY_DOC_STATUSES),
            )
        )
    ).scalar_one()

    sources = (
        await session.execute(
            select(TenderSource).where(TenderSource.owner_id == user.id)
        )
    ).scalars().all()
    source_by_id = {str(s.id): s for s in sources}

    pull_jobs = (
        await session.execute(
            select(Job).where(
                Job.type == "pull_source",
                Job.status.in_(_PULL_JOB_STATUSES),
            )
        )
    ).scalars().all()

    tender_pulls: list[TenderPullActivity] = []
    for job in pull_jobs:
        source_id = job.payload.get("source_id")
        if not source_id:
            continue
        source = source_by_id.get(str(source_id))
        if source is None:
            continue
        tender_pulls.append(
            TenderPullActivity(
                source_id=uuid.UUID(str(source_id)),
                source_name=source.name,
                status=job.status,
            )
        )

    return ActivityOut(
        documents_processing=lib_count + proj_count,
        tender_pulls=tender_pulls,
    )
