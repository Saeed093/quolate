"""Tenders router: filterable list, detail, correlation matches, badge."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.models import Tender, TenderSource, User
from app.db.session import get_session
from app.schemas import TenderOut
from app.tenders.correlation import (
    correlate_tender as _correlate_tender,
    correlate_tender_against_library,
)
from app.tenders.notifications import apply_criteria, count_saved_filter_matches

router = APIRouter(tags=["tenders"])


@router.get("/tenders", response_model=list[TenderOut])
async def list_tenders(
    keyword: str | None = None,
    tender_no: str | None = None,
    org_type: str | None = None,
    category: str | None = None,
    sector: str | None = None,
    organization: str | None = None,
    city: str | None = None,
    status: str | None = Query(default=None, description="open|closed"),
    closing_from: date | None = None,
    closing_to: date | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Tender]:
    stmt = (
        select(Tender)
        .join(TenderSource, Tender.source_id == TenderSource.id)
        .where(TenderSource.owner_id == user.id)
    )
    criteria = {
        "keyword": keyword,
        "tender_no": tender_no,
        "org_type": org_type,
        "category": category,
        "sector": sector,
        "organization": organization,
        "city": city,
        "status": status,
        "closing_from": closing_from,
        "closing_to": closing_to,
    }
    criteria = {k: v for k, v in criteria.items() if v is not None}
    stmt = apply_criteria(stmt, criteria)
    stmt = stmt.order_by(Tender.closing_date.is_(None), Tender.closing_date).limit(200)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


@router.post("/tenders/cleanup")
async def cleanup_tenders(
    body: dict | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete all but the newest N tenders (default: TENDER_KEEP_LIMIT)."""
    from app.tenders.cleanup import trim_tenders

    keep = None
    if body and body.get("keep") is not None:
        try:
            keep = max(0, int(body["keep"]))
        except (TypeError, ValueError):
            keep = None
    return await trim_tenders(session, user.id, keep=keep)


@router.get("/tenders/notifications/badge")
async def notification_badge(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    count = await count_saved_filter_matches(session, user.id)
    return {"count": count}


async def _get_owned_tender(
    tender_id: uuid.UUID, user: User, session: AsyncSession
) -> Tender:
    tender = (
        await session.execute(
            select(Tender)
            .join(TenderSource, Tender.source_id == TenderSource.id)
            .where(Tender.id == tender_id, TenderSource.owner_id == user.id)
        )
    ).scalar_one_or_none()
    if tender is None:
        raise HTTPException(status_code=404, detail="Tender not found")
    return tender


@router.get("/tenders/{tender_id}", response_model=TenderOut)
async def get_tender(
    tender_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Tender:
    return await _get_owned_tender(tender_id, user, session)


@router.get("/tenders/{tender_id}/matches")
async def tender_matches(
    tender_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    tender = await _get_owned_tender(tender_id, user, session)
    matches = await _correlate_tender(session, tender)
    library_matches = await correlate_tender_against_library(session, tender)
    return {
        "tender_id": str(tender.id),
        "count": len(matches) + len(library_matches),
        "matches": matches,
        "library_matches": library_matches,
    }
