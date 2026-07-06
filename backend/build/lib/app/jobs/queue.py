"""Job queue interface (Postgres-backed).

Isolated so a hosted queue can replace it later without touching callers.
Public surface: enqueue(), claim_next(), mark_done(), mark_failed().
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job

MAX_ATTEMPTS = 3


async def enqueue(
    session: AsyncSession, type: str, payload: dict, run_after: datetime | None = None
) -> Job:
    job = Job(type=type, payload=payload, status="queued", run_after=run_after)
    session.add(job)
    await session.flush()
    return job


async def claim_next(session: AsyncSession) -> Job | None:
    """Atomically claim the next runnable job (SKIP LOCKED)."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(Job)
        .where(Job.status == "queued")
        .where((Job.run_after.is_(None)) | (Job.run_after <= now))
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    await session.flush()
    return job


async def mark_done(session: AsyncSession, job_id: uuid.UUID) -> None:
    await session.execute(
        update(Job).where(Job.id == job_id).values(status="done", error=None)
    )


async def mark_failed(session: AsyncSession, job_id: uuid.UUID, error: str) -> None:
    result = await session.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        return
    if job.attempts >= MAX_ATTEMPTS:
        job.status = "failed"
    else:
        job.status = "queued"  # retry
    job.error = error[:4000]
