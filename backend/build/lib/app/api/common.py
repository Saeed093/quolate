"""Shared router helpers for owner-scoped access."""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, Project, Supplier, User


async def get_owned_project(
    project_id: uuid.UUID, user: User, session: AsyncSession
) -> Project:
    result = await session.execute(
        select(Project).where(
            Project.id == project_id, Project.owner_id == user.id
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        # 404 (not 403) so we never reveal existence of others' projects.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


async def get_owned_supplier(
    supplier_id: uuid.UUID, user: User, session: AsyncSession
) -> Supplier:
    result = await session.execute(
        select(Supplier)
        .join(Project, Supplier.project_id == Project.id)
        .where(Supplier.id == supplier_id, Project.owner_id == user.id)
    )
    supplier = result.scalar_one_or_none()
    if supplier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    return supplier


async def get_owned_document(
    document_id: uuid.UUID, user: User, session: AsyncSession
) -> Document:
    result = await session.execute(
        select(Document)
        .join(Project, Document.project_id == Project.id)
        .where(Document.id == document_id, Project.owner_id == user.id)
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document
