"""Saved filters router (owner-scoped)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.models import SavedFilter, User
from app.db.session import get_session
from app.schemas import SavedFilterCreate, SavedFilterOut

router = APIRouter(tags=["saved-filters"])


@router.get("/saved-filters", response_model=list[SavedFilterOut])
async def list_filters(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[SavedFilter]:
    rows = (
        await session.execute(
            select(SavedFilter)
            .where(SavedFilter.owner_id == user.id)
            .order_by(SavedFilter.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


@router.post("/saved-filters", response_model=SavedFilterOut, status_code=201)
async def create_filter(
    body: SavedFilterCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SavedFilter:
    sf = SavedFilter(owner_id=user.id, name=body.name, criteria=body.criteria)
    session.add(sf)
    await session.commit()
    await session.refresh(sf)
    return sf


@router.delete("/saved-filters/{filter_id}", status_code=204)
async def delete_filter(
    filter_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    sf = (
        await session.execute(
            select(SavedFilter).where(
                SavedFilter.id == filter_id, SavedFilter.owner_id == user.id
            )
        )
    ).scalar_one_or_none()
    if sf is None:
        raise HTTPException(status_code=404, detail="Filter not found")
    await session.delete(sf)
    await session.commit()
