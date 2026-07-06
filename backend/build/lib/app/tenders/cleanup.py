"""Trim old tenders to keep the database small.

Keeps the newest N tenders per owner (by advertise date, then created_at) and
deletes the rest — including their embeddings, downloaded tender documents
(rows cascade via FK) and the stored document blobs.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Tender, TenderDocument, TenderSource
from app.storage import storage

log = logging.getLogger("quolate.tenders.cleanup")


async def trim_tenders(
    session: AsyncSession, owner_id: uuid.UUID, *, keep: int | None = None
) -> dict:
    """Delete all but the newest `keep` tenders for an owner. Returns counts."""
    keep = keep if keep is not None else settings.tender_keep_limit
    keep = max(0, int(keep))

    ranked = (
        await session.execute(
            select(Tender.id)
            .join(TenderSource, Tender.source_id == TenderSource.id)
            .where(TenderSource.owner_id == owner_id)
            .order_by(
                Tender.advertise_date.desc().nulls_last(),
                Tender.created_at.desc(),
            )
        )
    ).scalars().all()

    doomed = ranked[keep:]
    if not doomed:
        return {"removed": 0, "kept": len(ranked)}

    # Delete stored attachment blobs first (fail-soft per blob).
    keys = (
        await session.execute(
            select(TenderDocument.storage_key).where(
                TenderDocument.tender_id.in_(doomed)
            )
        )
    ).scalars().all()
    for key in keys:
        try:
            await asyncio.to_thread(storage.delete, key)
        except Exception:
            log.warning("blob delete failed for %s", key, exc_info=True)

    # Tender rows cascade to tender_embeddings + tender_documents.
    await session.execute(delete(Tender).where(Tender.id.in_(doomed)))
    await session.commit()

    log.info("trimmed %d old tender(s), kept %d", len(doomed), keep)
    return {"removed": len(doomed), "kept": min(keep, len(ranked))}
