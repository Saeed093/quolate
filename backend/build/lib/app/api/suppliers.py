"""Suppliers router (owner-scoped via parent project)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import get_owned_project, get_owned_supplier
from app.auth.deps import get_current_user
from app.db.models import Supplier, User
from app.db.session import get_session
from app.schemas import SupplierCreate, SupplierOut, SupplierUpdate

router = APIRouter(tags=["suppliers"])


@router.get("/projects/{project_id}/suppliers", response_model=list[SupplierOut])
async def list_suppliers(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Supplier]:
    await get_owned_project(project_id, user, session)
    result = await session.execute(
        select(Supplier)
        .where(Supplier.project_id == project_id)
        .order_by(Supplier.created_at)
    )
    return list(result.scalars().all())


@router.post(
    "/projects/{project_id}/suppliers", response_model=SupplierOut, status_code=201
)
async def create_supplier(
    project_id: uuid.UUID,
    body: SupplierCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Supplier:
    await get_owned_project(project_id, user, session)
    supplier = Supplier(project_id=project_id, **body.model_dump())
    session.add(supplier)
    await session.commit()
    await session.refresh(supplier)
    return supplier


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
async def update_supplier(
    supplier_id: uuid.UUID,
    body: SupplierUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Supplier:
    supplier = await get_owned_supplier(supplier_id, user, session)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(supplier, key, value)
    await session.commit()
    await session.refresh(supplier)
    return supplier


@router.delete("/suppliers/{supplier_id}", status_code=204)
async def delete_supplier(
    supplier_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    supplier = await get_owned_supplier(supplier_id, user, session)
    await session.delete(supplier)
    await session.commit()
