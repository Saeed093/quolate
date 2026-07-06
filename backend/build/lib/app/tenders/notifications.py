"""Saved-filter matching -> in-app notification badge (no email in MVP)."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SavedFilter, Tender, TenderSource


def apply_criteria(stmt: Select, criteria: dict) -> Select:
    """Apply a saved-filter / query criteria dict to a Tender select."""
    keyword = criteria.get("keyword")
    if keyword:
        like = f"%{str(keyword).lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Tender.title).like(like),
                func.lower(Tender.organization).like(like),
                func.lower(Tender.raw_text).like(like),
            )
        )
    if criteria.get("tender_no"):
        stmt = stmt.where(Tender.tender_no == criteria["tender_no"])
    if criteria.get("org_type"):
        stmt = stmt.where(Tender.org_type == criteria["org_type"])
    if criteria.get("category"):
        stmt = stmt.where(Tender.category == criteria["category"])
    if criteria.get("city"):
        stmt = stmt.where(func.lower(Tender.city) == str(criteria["city"]).lower())
    if criteria.get("sector"):
        stmt = stmt.where(Tender.sector_tags.any(criteria["sector"]))
    if criteria.get("organization"):
        like = f"%{str(criteria['organization']).lower()}%"
        stmt = stmt.where(func.lower(Tender.organization).like(like))
    if criteria.get("closing_from"):
        stmt = stmt.where(Tender.closing_date >= criteria["closing_from"])
    if criteria.get("closing_to"):
        stmt = stmt.where(Tender.closing_date <= criteria["closing_to"])
    status = criteria.get("status")
    if status == "open":
        stmt = stmt.where(Tender.closing_date >= date.today())
    elif status == "closed":
        stmt = stmt.where(Tender.closing_date < date.today())
    if criteria.get("min_days_to_close") is not None:
        # Handled by caller when needed; kept simple here.
        pass
    return stmt


async def count_saved_filter_matches(
    session: AsyncSession, owner_id: uuid.UUID
) -> int:
    """Total tenders (across the owner's sources) matching any saved filter."""
    filters = (
        await session.execute(
            select(SavedFilter).where(SavedFilter.owner_id == owner_id)
        )
    ).scalars().all()
    matched: set = set()
    for f in filters:
        stmt = (
            select(Tender.id)
            .join(TenderSource, Tender.source_id == TenderSource.id)
            .where(TenderSource.owner_id == owner_id)
        )
        stmt = apply_criteria(stmt, f.criteria or {})
        ids = (await session.execute(stmt)).scalars().all()
        matched.update(ids)
    return len(matched)


async def saved_filter_matches(
    session: AsyncSession, owner_id: uuid.UUID, criteria: dict
) -> list[Tender]:
    stmt = (
        select(Tender)
        .join(TenderSource, Tender.source_id == TenderSource.id)
        .where(TenderSource.owner_id == owner_id)
    )
    stmt = apply_criteria(stmt, criteria or {})
    return list((await session.execute(stmt)).scalars().all())
