"""Tender job handlers (registered with the jobs worker)."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TenderSource
from app.jobs.registry import register
from app.tenders.scraper import pull_source


@register("pull_source")
async def pull_source_job(session: AsyncSession, payload: dict) -> None:
    source_id = uuid.UUID(payload["source_id"])
    source = (
        await session.execute(
            select(TenderSource).where(TenderSource.id == source_id)
        )
    ).scalar_one_or_none()
    if source is None:
        return
    await pull_source(session, source)
    await session.commit()

    # Auto-trim: keep only the newest N tenders for this owner.
    from app.tenders.cleanup import trim_tenders

    await trim_tenders(session, source.owner_id)
