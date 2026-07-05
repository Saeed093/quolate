"""Tender sources router: manage sources + pull-now (SSE progress stream)."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.models import TenderSource, User
from app.db.session import SessionLocal, get_session
from app.schemas import TenderSourceCreate, TenderSourceOut, TenderSourceUpdate
from app.tenders.adapters import adapter_names
from app.tenders.scraper import pull_source

log = logging.getLogger("quolate.tenders")
router = APIRouter(tags=["tender-sources"])


async def _get_owned_source(
    source_id: uuid.UUID, user: User, session: AsyncSession
) -> TenderSource:
    source = (
        await session.execute(
            select(TenderSource).where(
                TenderSource.id == source_id, TenderSource.owner_id == user.id
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.get("/tender-sources", response_model=list[TenderSourceOut])
async def list_sources(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[TenderSource]:
    rows = (
        await session.execute(
            select(TenderSource)
            .where(TenderSource.owner_id == user.id)
            .order_by(TenderSource.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


@router.post("/tender-sources", response_model=TenderSourceOut, status_code=201)
async def create_source(
    body: TenderSourceCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TenderSource:
    adapter = body.adapter if body.adapter in adapter_names() else "generic"
    source = TenderSource(
        owner_id=user.id,
        name=body.name,
        base_url=body.base_url,
        adapter=adapter,
        enabled=True,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


@router.patch("/tender-sources/{source_id}", response_model=TenderSourceOut)
async def update_source(
    source_id: uuid.UUID,
    body: TenderSourceUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TenderSource:
    source = await _get_owned_source(source_id, user, session)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(source, key, value)
    await session.commit()
    await session.refresh(source)
    return source


@router.delete("/tender-sources/{source_id}", status_code=204)
async def delete_source(
    source_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    source = await _get_owned_source(source_id, user, session)
    await session.delete(source)
    await session.commit()


@router.post("/tender-sources/{source_id}/pull-async")
async def pull_async(
    source_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Queue a pull as a background job; the worker runs it even if the user
    navigates away. Progress is reflected in the source's last_run/last_status."""
    from app.jobs import queue

    source = await _get_owned_source(source_id, user, session)
    job = await queue.enqueue(session, "pull_source", {"source_id": str(source.id)})
    await session.commit()
    return {"job_id": str(job.id), "status": "queued"}


@router.post("/tender-sources/{source_id}/pull")
async def pull_now(
    source_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # Verify ownership using the request-scoped session, then close it.
    # The long-running pull opens its own session so it outlives the
    # request dependency scope (which is closed when StreamingResponse starts).
    source = await _get_owned_source(source_id, user, session)
    source_id_val = source.id  # plain value — don't pass the ORM object

    progress_queue: asyncio.Queue[dict | None] = asyncio.Queue()

    def on_progress(event: dict) -> None:
        progress_queue.put_nowait(event)

    async def run_pull() -> None:
        # Open a fresh connection independent of the request lifecycle.
        async with SessionLocal() as bg_session:
            try:
                bg_source = (
                    await bg_session.execute(
                        select(TenderSource).where(TenderSource.id == source_id_val)
                    )
                ).scalar_one_or_none()
                if bg_source is None:
                    progress_queue.put_nowait(
                        {"phase": "done", "status": "failed", "error": "Source not found",
                         "created": 0, "updated": 0}
                    )
                    return
                await pull_source(bg_session, bg_source, delay=0, on_progress=on_progress)
                await bg_session.commit()
            except Exception as exc:
                log.exception("pull_source background task failed: %r", exc)
                progress_queue.put_nowait(
                    {"phase": "done", "status": "failed", "error": str(exc)[:300],
                     "created": 0, "updated": 0}
                )
            finally:
                progress_queue.put_nowait(None)

    async def event_stream():
        task = asyncio.create_task(run_pull())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(progress_queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
