"""Create BOM lines from quotation extraction when the project has no BOM yet."""
from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BomItem


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _line_items_from_fields(fields: list[dict]) -> list[dict]:
    """Fallback when the model returns fields but omits line_items."""
    by_line: dict[int, dict] = {}
    orphan_idx = 0
    for f in fields:
        base = (f.get("field_type") or "").split(":", 1)[0]
        if base != "unit_price" or f.get("value_num") is None:
            continue
        line_no = f.get("bom_line_no")
        if line_no is None:
            orphan_idx += 1
            line_no = 10_000 + orphan_idx
        bucket = by_line.setdefault(
            int(line_no),
            {
                "line_no": int(line_no),
                "part_name": None,
                "spec_requirement": None,
                "quantity": None,
                "unit_price": f.get("value_num"),
            },
        )
        snippet = (f.get("source_snippet") or "").strip()
        if snippet and not bucket.get("part_name"):
            bucket["part_name"] = snippet[:200]
    items = [v for v in by_line.values() if v.get("part_name")]
    return sorted(items, key=lambda x: x["line_no"])


async def _next_line_no(session: AsyncSession, project_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(BomItem.line_no), 0)).where(
            BomItem.project_id == project_id
        )
    )
    return int(result.scalar_one()) + 1


async def bootstrap_bom_from_extraction(
    session: AsyncSession,
    project_id: uuid.UUID,
    extraction: dict,
) -> tuple[dict[int, uuid.UUID], int]:
    """Ensure BOM rows exist from quotation line_items when the project BOM is empty.

    Returns (line_no -> bom_item_id, count_created).
    """
    result = await session.execute(
        select(BomItem)
        .where(BomItem.project_id == project_id)
        .order_by(BomItem.line_no)
    )
    existing = list(result.scalars().all())
    line_to_item: dict[int, uuid.UUID] = {b.line_no: b.id for b in existing}
    if existing:
        return line_to_item, 0

    line_items = list(extraction.get("line_items") or [])
    if not line_items:
        line_items = _line_items_from_fields(extraction.get("fields") or [])
    if not line_items:
        return line_to_item, 0

    created = 0
    base = await _next_line_no(session, project_id)
    for offset, item in enumerate(line_items):
        part_name = (item.get("part_name") or "").strip()
        if not part_name:
            continue
        raw_line = item.get("line_no")
        line_no = int(raw_line) if raw_line is not None else base + offset
        bom = BomItem(
            project_id=project_id,
            line_no=line_no,
            part_name=part_name,
            spec_requirement=item.get("spec_requirement"),
            quantity=_to_decimal(item.get("quantity")),
            target_price=_to_decimal(
                item.get("unit_price") if item.get("unit_price") is not None else item.get("target_price")
            ),
            notes=item.get("notes"),
        )
        session.add(bom)
        await session.flush()
        line_to_item[line_no] = bom.id
        created += 1

    return line_to_item, created
