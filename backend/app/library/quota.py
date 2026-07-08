"""Library storage quota helpers."""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import LibraryDocument
from app.storage import storage


async def backfill_missing_sizes(session: AsyncSession, owner_id: uuid.UUID) -> None:
    """Populate size_bytes from disk for legacy rows (pre-migration uploads)."""
    result = await session.execute(
        select(LibraryDocument).where(
            LibraryDocument.owner_id == owner_id,
            LibraryDocument.size_bytes == 0,
        )
    )
    docs = list(result.scalars().all())
    if not docs:
        return

    for doc in docs:
        try:
            data = await asyncio.to_thread(storage.get, doc.storage_key)
            doc.size_bytes = len(data)
        except FileNotFoundError:
            doc.size_bytes = 0
    await session.flush()


async def library_usage_bytes(session: AsyncSession, owner_id: uuid.UUID) -> int:
    await backfill_missing_sizes(session, owner_id)
    total = (
        await session.execute(
            select(func.coalesce(func.sum(LibraryDocument.size_bytes), 0)).where(
                LibraryDocument.owner_id == owner_id
            )
        )
    ).scalar_one()
    return int(total or 0)


def library_quota_bytes() -> int:
    return int(settings.library_quota_bytes)
