"""Assemble a priced quotation version from the project's demand + matrix.

The comparison matrix (app.matrix.builder) already picks the cheapest covering
supplier per BOM line (``best_supplier_id``) and computes its landed cost incl.
Pakistan duty. A sell-side quotation is a projection over that: take the best
landed cost as unit cost, add the project margin, round to a whole unit, and
sum with optional GST. Lines the matrix can't cost are flagged as gaps for the
user to price manually or remove at review.
"""
from __future__ import annotations

import re
import uuid
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Project,
    Quotation,
    QuotationLine,
    QuotationVersion,
)
from app.matrix.builder import build_matrix


def _dec(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None


def _round_whole(value: Decimal) -> Decimal:
    """Round to the nearest whole currency unit (half-up, not banker's)."""
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def price_unit(unit_cost: Decimal | None, margin_pct: Decimal) -> Decimal | None:
    """Sell price for one unit = cost * (1 + margin), rounded to a whole unit."""
    if unit_cost is None:
        return None
    return _round_whole(unit_cost * (Decimal(1) + margin_pct))


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug or "project"


def compute_totals(
    lines: list[QuotationLine],
    *,
    gst_enabled: bool,
    gst_pct: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return (subtotal, tax_total, grand_total) from line totals."""
    subtotal = sum((_dec(line.line_total) or Decimal(0) for line in lines), Decimal(0))
    tax_total = _round_whole(subtotal * gst_pct) if gst_enabled else Decimal(0)
    return subtotal, tax_total, subtotal + tax_total


def recompute_line(line: QuotationLine, margin_pct: Decimal) -> None:
    """Recompute unit_price + line_total for a line from its cost and qty.

    A manual unit_price already set on the line is preserved (cost_source
    'manual'); otherwise it is derived from unit_cost + margin.
    """
    qty = _dec(line.qty) or Decimal(1)
    if line.cost_source == "manual":
        unit_price = _dec(line.unit_price)
    else:
        unit_price = price_unit(_dec(line.unit_cost), margin_pct)
        line.unit_price = unit_price
    line.gap_flag = unit_price is None
    line.line_total = (unit_price * qty) if unit_price is not None else None


async def _next_seq(session: AsyncSession, project_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(Quotation.seq), 0)).where(
            Quotation.project_id == project_id
        )
    )
    return int(result.scalar_one()) + 1


async def _assemble_lines_from_matrix(
    session: AsyncSession, project: Project, margin_pct: Decimal
) -> list[QuotationLine]:
    """Build QuotationLine rows (unpersisted) from the current BOM + matrix."""
    matrix = await build_matrix(session, project, currency=project.base_currency)
    lines: list[QuotationLine] = []
    for row in matrix["rows"]:
        cells = row.get("cells", {})
        # The user's explicit pick on the Compare page wins when it has a usable
        # landed cost; otherwise fall back to the cheapest covering supplier.
        selected_sid = row.get("selected_supplier_id")
        best_sid = row.get("best_supplier_id")
        if selected_sid and (cells.get(selected_sid) or {}).get("landed") is not None:
            chosen_sid = selected_sid
        else:
            chosen_sid = best_sid
        cell = cells.get(chosen_sid) if chosen_sid else None
        unit_cost = _dec(cell.get("landed")) if cell else None
        cost_source = None
        if cell is not None and unit_cost is not None:
            doc_id = cell.get("document_id")
            cost_source = f"supplier_doc:{doc_id}" if doc_id else "supplier_doc"
        qty = _dec(row.get("quantity")) or Decimal(1)
        line = QuotationLine(
            line_no=row["line_no"],
            description=row["part_name"],
            spec=row.get("spec_requirement"),
            qty=qty,
            unit_cost=unit_cost,
            cost_source=cost_source,
        )
        recompute_line(line, margin_pct)
        lines.append(line)
    return lines


async def create_quotation(
    session: AsyncSession, project: Project, *, title: str | None = None
) -> Quotation:
    """Create a quotation with a priced draft version 1 from the current BOM.

    The caller commits. Returns the Quotation with `.versions[0].lines` populated.
    """
    margin_pct = _dec(project.margin_pct) or Decimal(0)
    gst_pct = _dec(project.gst_pct) or Decimal(0)
    terms = dict(project.terms or {})
    validity_days = terms.get("validity_days")

    seq = await _next_seq(session, project.id)
    quote_no = f"{slugify(project.name)}-QUO-{seq:04d}"
    quotation = Quotation(
        project_id=project.id, quote_no=quote_no, seq=seq, title=title, status="draft"
    )
    session.add(quotation)
    await session.flush()  # assign quotation.id

    lines = await _assemble_lines_from_matrix(session, project, margin_pct)
    version = QuotationVersion(
        quotation_id=quotation.id,
        version_no=1,
        status="draft",
        currency=project.base_currency,
        margin_pct=margin_pct,
        gst_enabled=bool(project.gst_enabled),
        gst_pct=gst_pct,
        validity_days=int(validity_days) if isinstance(validity_days, (int, float)) else None,
        terms_snapshot=terms,
    )
    subtotal, tax_total, grand_total = compute_totals(
        lines, gst_enabled=bool(project.gst_enabled), gst_pct=gst_pct
    )
    version.subtotal = subtotal
    version.tax_total = tax_total
    version.grand_total = grand_total
    # `version` is pending, so assigning its collection needs no DB load; we do
    # NOT touch quotation.versions (persistent -> would trigger a sync lazy load).
    version.lines = lines
    session.add(version)
    await session.flush()
    return quotation
