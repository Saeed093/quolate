"""Asyncio background worker loop + a synchronous test driver."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.db.session import SessionLocal
from app.jobs import queue
from app.jobs.registry import ensure_handlers_loaded, get_handler

log = logging.getLogger("quolate.jobs")

POLL_INTERVAL_SECONDS = 1.0


async def _run_one() -> bool:
    """Claim and run a single job. Returns True if a job was processed."""
    ensure_handlers_loaded()
    async with SessionLocal() as session:
        job = await queue.claim_next(session)
        if job is None:
            await session.commit()
            return False
        job_id = job.id
        job_type = job.type
        payload = dict(job.payload or {})
        await session.commit()

    handler = get_handler(job_type)
    if handler is None:
        async with SessionLocal() as session:
            await queue.mark_failed(session, job_id, f"no handler for {job_type}")
            await session.commit()
        return True

    try:
        async with SessionLocal() as session:
            await handler(session, payload)
            await queue.mark_done(session, job_id)
            await session.commit()
    except Exception as exc:  # fail soft, never crash the worker
        log.exception("job %s (%s) failed", job_id, job_type)
        async with SessionLocal() as session:
            await queue.mark_failed(session, job_id, repr(exc))
            await session.commit()
    return True


async def drain() -> int:
    """Process all runnable jobs; return count. Used by tests."""
    count = 0
    while await _run_one():
        count += 1
    return count


@dataclass
class WorkerHandle:
    task: asyncio.Task
    _stop: asyncio.Event

    async def stop(self) -> None:
        self._stop.set()
        try:
            await asyncio.wait_for(self.task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self.task.cancel()


async def _loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            processed = await _run_one()
        except Exception:
            log.exception("worker loop error")
            processed = False
        if not processed:
            try:
                await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass


async def requeue_stale_jobs() -> int:
    """Requeue jobs orphaned in 'running' by a previous process crash/restart.

    Safe with a single worker process: anything 'running' at startup is a corpse.
    Returns the number of requeued jobs.
    """
    from sqlalchemy import update

    from app.db.models import Job

    async with SessionLocal() as session:
        result = await session.execute(
            update(Job).where(Job.status == "running").values(status="queued")
        )
        await session.commit()
        count = result.rowcount or 0
    if count:
        log.warning("requeued %d stale running job(s) from a previous run", count)
    return count


async def start_worker() -> WorkerHandle:
    await requeue_stale_jobs()
    stop = asyncio.Event()
    task = asyncio.create_task(_loop(stop))
    return WorkerHandle(task=task, _stop=stop)
