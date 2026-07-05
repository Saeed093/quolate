"""Fields router: confirm/edit extracted fields, propagate to quotes."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import get_owned_document
from app.auth.deps import get_current_user
from app.db.models import ExtractedField, Quote, User
from app.db.session import get_session
from app.schemas import ExtractedFieldOut, FieldUpdate

router = APIRouter(tags=["fields"])

_VALID_STATUS = {"auto", "confirmed", "edited", "rejected"}


@router.patch("/fields/{field_id}", response_model=ExtractedFieldOut)
async def update_field(
    field_id: uuid.UUID,
    body: FieldUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ExtractedField:
    result = await session.execute(
        select(ExtractedField).where(ExtractedField.id == field_id)
    )
    field = result.scalar_one_or_none()
    if field is None:
        raise HTTPException(status_code=404, detail="Field not found")

    # Owner check via the parent document.
    await get_owned_document(field.document_id, user, session)

    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in _VALID_STATUS:
        raise HTTPException(status_code=422, detail="Invalid status")

    for key, value in data.items():
        setattr(field, key, value)

    # If the user edits a value, default status to 'edited' unless explicitly set.
    if ("value_num" in data or "value_text" in data) and "status" not in data:
        field.status = "edited"

    await _propagate_to_quote(session, field)
    await session.commit()
    await session.refresh(field)
    return field


async def _propagate_to_quote(session: AsyncSession, field: ExtractedField) -> None:
    base_type = field.field_type.split(":", 1)[0]
    column = {
        "unit_price": "unit_price",
        "moq": "moq",
        "lead_time_days": "lead_time_days",
        "incoterms": "incoterms",
    }.get(base_type)
    if column is None or field.supplier_id is None:
        return

    conditions = [
        Quote.document_id == field.document_id,
        Quote.supplier_id == field.supplier_id,
        Quote.superseded_by.is_(None),
    ]
    if field.bom_item_id is None:
        conditions.append(Quote.bom_item_id.is_(None))
    else:
        conditions.append(Quote.bom_item_id == field.bom_item_id)

    result = await session.execute(select(Quote).where(*conditions))
    quote = result.scalars().first()
    if quote is None:
        return

    if field.status == "rejected":
        return
    if column in {"unit_price", "moq"}:
        setattr(quote, column, field.value_num)
    elif column == "lead_time_days":
        setattr(quote, column, int(field.value_num) if field.value_num is not None else None)
    elif column == "incoterms":
        setattr(quote, column, field.value_text)
