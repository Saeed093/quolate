"""Build the fully-computed comparison matrix (suppliers x BOM lines).

All math is deterministic and server-side (spec section 5). Returns a plain
JSON-serialisable dict; landed cost is computed here, never stored.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BomItem, Document, ExtractedField, Project, Quote, Supplier
from app.matrix.fx import UnknownCurrency, convert
from app.matrix.landed_cost import landed_unit_cost, spread_pct, to_decimal

LOW_CONFIDENCE = 0.7


def resolve_assumptions(project: Project, overrides: dict | None = None) -> dict:
    """Merge project landed_cost_defaults with per-request overrides."""
    defaults = dict(project.landed_cost_defaults or {})
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    return {
        "duty_pct": to_decimal(
            overrides.get("duty_pct", defaults.get("duty_pct")), Decimal(0)
        )
        or Decimal(0),
        "freight_per_unit": to_decimal(
            overrides.get("freight_per_unit", defaults.get("freight_per_unit")),
            Decimal(0),
        )
        or Decimal(0),
        "lc_pct": to_decimal(
            overrides.get("lc_pct", defaults.get("lc_pct")), Decimal(0)
        )
        or Decimal(0),
        "fx_overrides": defaults.get("fx_overrides") or {},
    }


def _num(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _cell_confidence_state(fields: list[ExtractedField]) -> str:
    """verify when any backing field is still auto and below threshold."""
    for f in fields:
        conf = float(f.confidence) if f.confidence is not None else None
        if f.status not in ("confirmed", "edited") and (
            conf is None or conf < LOW_CONFIDENCE
        ):
            return "verify"
    return "ok"


async def build_matrix(
    session: AsyncSession,
    project: Project,
    *,
    currency: str | None = None,
    overrides: dict | None = None,
) -> dict:
    target_ccy = (currency or project.base_currency or "USD").upper()
    assumptions = resolve_assumptions(project, overrides)
    fx_overrides = assumptions["fx_overrides"]

    bom_rows = (
        (
            await session.execute(
                select(BomItem)
                .where(BomItem.project_id == project.id)
                .order_by(BomItem.line_no)
            )
        )
        .scalars()
        .all()
    )
    suppliers = (
        (
            await session.execute(
                select(Supplier)
                .where(Supplier.project_id == project.id)
                .order_by(Supplier.name)
            )
        )
        .scalars()
        .all()
    )

    # Active (non-superseded) quotes keyed by (supplier_id, bom_item_id).
    quotes = (
        (
            await session.execute(
                select(Quote).where(
                    Quote.project_id == project.id,
                    Quote.superseded_by.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    quote_map: dict[tuple[uuid.UUID, uuid.UUID | None], Quote] = {}
    for q in quotes:
        key = (q.supplier_id, q.bom_item_id)
        prev = quote_map.get(key)
        if prev is None or (q.created_at and prev.created_at and q.created_at > prev.created_at):
            quote_map[key] = q

    # Extracted fields for provenance + confidence, keyed the same way.
    fields = (
        (
            await session.execute(
                select(ExtractedField)
                .join(Document, ExtractedField.document_id == Document.id)
                .where(Document.project_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    field_map: dict[tuple[uuid.UUID | None, uuid.UUID | None], list[ExtractedField]] = {}
    for f in fields:
        field_map.setdefault((f.supplier_id, f.bom_item_id), []).append(f)

    rows: list[dict] = []
    all_landed: list[Decimal] = []
    for item in bom_rows:
        cells: dict[str, dict] = {}
        row_landed: list[tuple[uuid.UUID, Decimal]] = []
        for sup in suppliers:
            quote = quote_map.get((sup.id, item.id))
            backing = field_map.get((sup.id, item.id), [])
            field_ids = [str(f.id) for f in backing]
            if quote is None:
                cells[str(sup.id)] = {
                    "supplier_id": str(sup.id),
                    "quote_id": None,
                    "document_id": None,
                    "fob": None,
                    "landed": None,
                    "currency": target_ccy,
                    "moq": None,
                    "lead_time_days": None,
                    "confidence_state": "gap",
                    "best_value": False,
                    "field_ids": field_ids,
                }
                continue

            unit_price = to_decimal(quote.unit_price)
            quote_ccy = (quote.currency or target_ccy).upper()
            fob: Decimal | None = None
            landed: Decimal | None = None
            conv_error = False
            if unit_price is not None:
                try:
                    fob = convert(unit_price, quote_ccy, target_ccy, fx_overrides)
                    landed = landed_unit_cost(
                        fob,
                        duty_pct=assumptions["duty_pct"],
                        freight_per_unit=assumptions["freight_per_unit"],
                        lc_pct=assumptions["lc_pct"],
                    )
                except UnknownCurrency:
                    conv_error = True

            state = _cell_confidence_state(backing)
            if conv_error and state == "ok":
                state = "verify"

            if landed is not None:
                row_landed.append((sup.id, landed))
                all_landed.append(landed)

            cells[str(sup.id)] = {
                "supplier_id": str(sup.id),
                "quote_id": str(quote.id),
                "document_id": str(quote.document_id) if quote.document_id else None,
                "fob": _num(fob),
                "landed": _num(landed),
                "currency": target_ccy,
                "moq": _num(to_decimal(quote.moq)),
                "lead_time_days": quote.lead_time_days,
                "confidence_state": state,
                "best_value": False,
                "field_ids": field_ids,
            }

        best_supplier_id: str | None = None
        if row_landed:
            best_sid, _best = min(row_landed, key=lambda kv: kv[1])
            best_supplier_id = str(best_sid)
            cells[best_supplier_id]["best_value"] = True

        rows.append(
            {
                "bom_item_id": str(item.id),
                "line_no": item.line_no,
                "part_name": item.part_name,
                "spec_requirement": item.spec_requirement,
                "quantity": _num(to_decimal(item.quantity)),
                "target_price": _num(to_decimal(item.target_price)),
                "best_supplier_id": best_supplier_id,
                "spread_pct": _num(spread_pct([lv for _, lv in row_landed])),
                "cells": cells,
            }
        )

    docs_parsed = (
        await session.execute(
            select(Document).where(
                Document.project_id == project.id,
                Document.status.in_(("parsed", "needs_review")),
            )
        )
    ).scalars().all()
    fields_needing_review = sum(
        1
        for f in fields
        if f.status == "auto"
        and f.confidence is not None
        and float(f.confidence) < LOW_CONFIDENCE
    )

    summary = {
        "lines_total": len(bom_rows),
        "suppliers_total": len(suppliers),
        "docs_parsed": len(docs_parsed),
        "fields_needing_review": fields_needing_review,
        "lowest_landed": _num(min(all_landed)) if all_landed else None,
        "overall_spread_pct": _num(spread_pct(all_landed)),
    }

    result = {
        "project_id": str(project.id),
        "currency": target_ccy,
        "assumptions": {
            "duty_pct": _num(assumptions["duty_pct"]),
            "freight_per_unit": _num(assumptions["freight_per_unit"]),
            "lc_pct": _num(assumptions["lc_pct"]),
            "fx_overrides": fx_overrides,
        },
        "suppliers": [
            {"id": str(s.id), "name": s.name, "country": s.country} for s in suppliers
        ],
        "rows": rows,
        "summary": summary,
    }
    result["matrix_hash"] = matrix_hash(result)
    return result


def matrix_hash(matrix: dict) -> str:
    """Stable hash of the matrix content (excludes any existing hash)."""
    payload = {k: v for k, v in matrix.items() if k != "matrix_hash"}
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
