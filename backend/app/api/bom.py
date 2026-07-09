"""BOM router (owner-scoped) incl. TSV paste import."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import get_owned_project
from app.auth.deps import get_current_user
from app.bom_parser import parse_bom_tsv
from app.db.models import BomItem, User
from app.db.session import get_session
from app.duty.classifier import ClassificationInputError, classify_hs_code
from app.duty.schemas import HsClassificationOut
from app.llm.json_enforce import SchemaEnforceError
from app.schemas import (
    BomItemCreate,
    BomItemOut,
    BomItemUpdate,
    BomPasteRequest,
)

router = APIRouter(tags=["bom"])


async def _next_line_no(session: AsyncSession, project_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(BomItem.line_no), 0)).where(
            BomItem.project_id == project_id
        )
    )
    return int(result.scalar_one()) + 1


@router.get("/projects/{project_id}/bom", response_model=list[BomItemOut])
async def list_bom(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[BomItem]:
    await get_owned_project(project_id, user, session)
    result = await session.execute(
        select(BomItem)
        .where(BomItem.project_id == project_id)
        .order_by(BomItem.line_no)
    )
    return list(result.scalars().all())


@router.post("/projects/{project_id}/bom", response_model=BomItemOut, status_code=201)
async def create_bom_item(
    project_id: uuid.UUID,
    body: BomItemCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BomItem:
    await get_owned_project(project_id, user, session)
    line_no = body.line_no or await _next_line_no(session, project_id)
    item = BomItem(
        project_id=project_id,
        line_no=line_no,
        part_name=body.part_name,
        spec_requirement=body.spec_requirement,
        quantity=body.quantity,
        target_price=body.target_price,
        notes=body.notes,
        hs_code=body.hs_code,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.post(
    "/projects/{project_id}/bom/paste",
    response_model=list[BomItemOut],
    status_code=201,
)
async def paste_bom(
    project_id: uuid.UUID,
    body: BomPasteRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[BomItem]:
    await get_owned_project(project_id, user, session)
    parsed = parse_bom_tsv(body.text, has_header=body.has_header)
    base = await _next_line_no(session, project_id)
    items: list[BomItem] = []
    for offset, rec in enumerate(parsed):
        item = BomItem(
            project_id=project_id,
            line_no=base + offset,
            part_name=rec["part_name"],
            spec_requirement=rec.get("spec_requirement"),
            quantity=rec.get("quantity"),
            target_price=rec.get("target_price"),
            notes=rec.get("notes"),
        )
        session.add(item)
        items.append(item)
    await session.commit()
    for item in items:
        await session.refresh(item)
    return items


@router.post(
    "/projects/{project_id}/bom/{item_id}/classify-hs",
    response_model=HsClassificationOut,
)
async def classify_bom_hs(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> HsClassificationOut:
    """LLM-suggest HS code candidates for one BOM line.

    Suggestions only — the user applies a candidate via PATCH /bom/{item_id}.
    """
    from fastapi import HTTPException

    await get_owned_project(project_id, user, session)
    result = await session.execute(
        select(BomItem).where(
            BomItem.id == item_id, BomItem.project_id == project_id
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="BOM item not found")

    text = " ".join(
        part
        for part in (item.part_name, item.spec_requirement, item.notes)
        if part
    )
    try:
        return await classify_hs_code(session, text=text, owner_id=user.id)
    except ClassificationInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SchemaEnforceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.patch("/bom/{item_id}", response_model=BomItemOut)
async def update_bom_item(
    item_id: uuid.UUID,
    body: BomItemUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BomItem:
    result = await session.execute(select(BomItem).where(BomItem.id == item_id))
    item = result.scalar_one_or_none()
    if item is not None:
        await get_owned_project(item.project_id, user, session)
    if item is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="BOM item not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await session.commit()
    await session.refresh(item)
    return item


@router.delete("/bom/{item_id}", status_code=204)
async def delete_bom_item(
    item_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    result = await session.execute(select(BomItem).where(BomItem.id == item_id))
    item = result.scalar_one_or_none()
    if item is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="BOM item not found")
    await get_owned_project(item.project_id, user, session)
    await session.delete(item)
    await session.commit()
