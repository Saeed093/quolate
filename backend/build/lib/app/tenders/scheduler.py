"""APScheduler: daily tender pull at SCRAPE_CRON (local time).

Enqueues a `pull_source` job for every enabled source so the existing worker
does the work. # TODO(cloud): replace with a hosted cron.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.config import settings
from app.db.models import TenderSource
from app.db.session import SessionLocal
from app.jobs import queue

log = logging.getLogger("quolate.scheduler")


async def enqueue_all_enabled_sources() -> int:
    async with SessionLocal() as session:
        sources = (
            await session.execute(
                select(TenderSource).where(TenderSource.enabled.is_(True))
            )
        ).scalars().all()
        for s in sources:
            await queue.enqueue(session, "pull_source", {"source_id": str(s.id)})
        await session.commit()
        return len(sources)


def _parse_cron(expr: str) -> dict:
    parts = expr.split()
    if len(parts) != 5:
        # Default: 07:00 daily.
        return {"minute": "0", "hour": "7"}
    minute, hour, day, month, dow = parts
    return {
        "minute": minute,
        "hour": hour,
        "day": day,
        "month": month,
        "day_of_week": dow,
    }


def start_scheduler():
    """Create and start an AsyncIOScheduler. Returns the scheduler or None."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except Exception as exc:  # optional dependency
        log.warning("APScheduler unavailable: %r", exc)
        return None

    scheduler = AsyncIOScheduler()
    trigger = CronTrigger(**_parse_cron(settings.scrape_cron))

    async def _job() -> None:
        try:
            n = await enqueue_all_enabled_sources()
            log.info("scheduled tender pull enqueued %d sources", n)
        except Exception:
            log.exception("scheduled tender pull failed")

    scheduler.add_job(_job, trigger, id="daily_tender_pull", replace_existing=True)
    scheduler.start()
    return scheduler
