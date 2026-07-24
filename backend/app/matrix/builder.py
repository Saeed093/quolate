"""Build the fully-computed comparison matrix (suppliers x BOM lines).

All math is deterministic and server-side (spec section 5). Returns a plain
JSON-serialisable dict; landed cost is computed here, never stored.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BomItem, Document, ExtractedField, Project, Quote, Supplier
from app.duty.engine import DutyBreakdown, compute_duty_stack
from app.duty.resolver import ResolvedLevy, resolve_rates
from app.matrix.fx import UnknownCurrency, convert
from app.matrix.fx_live import get_pkr_rate
from app.matrix.landed_cost import landed_unit_cost, spread_pct, to_decimal

LOW_CONFIDENCE = 0.7

# field_type values that are surfaced as named keys in the cell dict
_NAMED_EXTRA_TYPES = {"payment_terms", "warranty", "validity_days"}


def _extra_fields_from_backing(backing: list[ExtractedField]) -> dict:
    """Extract named extra fields and spec:* fields from backing ExtractedField rows.

    Returns a dict with keys: payment_terms, warranty, validity_days (str or None),
    plus any spec:<name> keys.
    """
    result: dict[str, str | None] = {}
    for f in backing:
        ft = f.field_type
        if ft in _NAMED_EXTRA_TYPES and ft not in result:
            if ft == "validity_days" and f.value_num is not None:
                result[ft] = f"{int(f.value_num)} days"
            else:
                result[ft] = f.value_text
        elif ft.startswith("spec:") and ft not in result:
            val = f.value_text
            if val is None and f.value_num is not None:
                val = str(f.value_num)
                if f.unit:
                    val = f"{val} {f.unit}"
            result[ft] = val
    return result


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


def _term(line_val, doc_val):
    """Line-level term wins; fall back to the document-level value."""
    return line_val if line_val is not None else doc_val


def _has_configured_rates(resolved: dict[str, ResolvedLevy]) -> bool:
    """True when at least one levy came from an actual rate-table row.

    The resolver returns zero-rate defaults (source_row_id=None) instead of
    raising when no rates are ingested for an HS code — treat that as "no
    statutory data" and fall back to the flat duty assumption.
    """
    return any(r.source_row_id is not None for r in resolved.values())


def _duty_breakdown_dict(breakdown: DutyBreakdown, fx_rate: Decimal) -> dict:
    return {
        "fx_rate": _num(fx_rate),
        "assessed_value_pkr": _num(breakdown.assessed_value_pkr),
        "total_duty_tax_pkr": _num(breakdown.total_duty_tax_pkr),
        "levies": [
            {
                "levy_type": line.levy_type,
                "label": line.label,
                "rate": _num(line.rate),
                "amount_pkr": _num(line.amount_pkr),
            }
            for line in breakdown.lines
        ],
    }


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
    fx_rate: float | None = None,
    display_rate: float | None = None,
) -> dict:
    target_ccy = (currency or project.base_currency or "USD").upper()
    assumptions = resolve_assumptions(project, overrides)
    fx_overrides = assumptions["fx_overrides"]

    # A user-supplied display rate ("1 USD = X <target>") overrides the bundled
    # rate for the display currency only, so the whole matrix reflects the rate
    # shown in the currency box. USD is the rate-table base, so it needs no rate.
    if display_rate and display_rate > 0 and target_ccy != "USD":
        fx_overrides = {**fx_overrides, target_ccy: display_rate}

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

    # Statutory Pakistan duty: resolve PKR/USD FX + rate tables once per build
    # for every distinct HS code on the BOM. Lines without an HS code (or with
    # no ingested rates) keep the flat duty_pct assumption.
    hs_codes = {
        item.hs_code.strip() for item in bom_rows if item.hs_code and item.hs_code.strip()
    }
    duty_fx: Decimal | None = None
    duty_fx_source: str | None = None
    duty_as_of: date | None = None
    resolved_by_hs: dict[str, dict[str, ResolvedLevy]] = {}
    if hs_codes:
        duty_as_of = date.today()
        if fx_rate is not None:
            duty_fx = to_decimal(fx_rate)
            duty_fx_source = "override"
        if duty_fx is None or duty_fx <= 0:
            live = await get_pkr_rate("USD")
            duty_fx = live.rate
            duty_fx_source = live.source
        for code in hs_codes:
            resolved_by_hs[code] = await resolve_rates(
                session,
                hs_code=code,
                importer_category=None,
                atl_status=None,
                as_of_date=duty_as_of,
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

    # Document-level (bom_item_id=None) quotes/fields carry quotation-wide terms
    # (incoterms, lead time, payment terms...) that apply to every line.
    doc_level: dict[uuid.UUID, tuple[Quote | None, dict]] = {
        sup.id: (
            quote_map.get((sup.id, None)),
            _extra_fields_from_backing(field_map.get((sup.id, None), [])),
        )
        for sup in suppliers
    }

    rows: list[dict] = []
    all_landed: list[Decimal] = []
    for item in bom_rows:
        cells: dict[str, dict] = {}
        row_landed: list[tuple[uuid.UUID, Decimal]] = []
        row_hs = (item.hs_code or "").strip() or None
        row_resolved = resolved_by_hs.get(row_hs) if row_hs else None
        row_statutory = row_resolved is not None and _has_configured_rates(row_resolved)
        for sup in suppliers:
            quote = quote_map.get((sup.id, item.id))
            backing = field_map.get((sup.id, item.id), [])
            field_ids = [str(f.id) for f in backing]
            extra = _extra_fields_from_backing(backing)
            spec_fields = {k: v for k, v in extra.items() if k.startswith("spec:")}
            doc_quote, doc_extra = doc_level[sup.id]

            unit_price = to_decimal(quote.unit_price) if quote is not None else None
            # A quote without a unit price is still a gap for comparison purposes.
            if quote is None or unit_price is None:
                source_quote = quote or doc_quote
                cells[str(sup.id)] = {
                    "supplier_id": str(sup.id),
                    "quote_id": str(quote.id) if quote is not None else None,
                    "document_id": (
                        str(source_quote.document_id)
                        if source_quote is not None and source_quote.document_id
                        else None
                    ),
                    "fob": None,
                    "landed": None,
                    "hs_code": row_hs,
                    "duty": None,
                    "duty_source": None,
                    "duty_breakdown": None,
                    "currency": target_ccy,
                    "moq": _num(
                        to_decimal(
                            _term(
                                quote.moq if quote is not None else None,
                                doc_quote.moq if doc_quote is not None else None,
                            )
                        )
                    ),
                    "lead_time_days": _term(
                        quote.lead_time_days if quote is not None else None,
                        doc_quote.lead_time_days if doc_quote is not None else None,
                    ),
                    "incoterms": _term(
                        quote.incoterms if quote is not None else None,
                        doc_quote.incoterms if doc_quote is not None else None,
                    ),
                    "valid_until": _term(
                        quote.valid_until.isoformat()
                        if quote is not None and quote.valid_until
                        else None,
                        doc_quote.valid_until.isoformat()
                        if doc_quote is not None and doc_quote.valid_until
                        else None,
                    ),
                    "payment_terms": _term(
                        extra.get("payment_terms"), doc_extra.get("payment_terms")
                    ),
                    "warranty": _term(extra.get("warranty"), doc_extra.get("warranty")),
                    "validity_days": _term(
                        extra.get("validity_days"), doc_extra.get("validity_days")
                    ),
                    "extra_fields": spec_fields,
                    "confidence_state": "gap",
                    "best_value": False,
                    "field_ids": field_ids,
                }
                continue
            quote_ccy = (quote.currency or target_ccy).upper()
            fob: Decimal | None = None
            landed: Decimal | None = None
            duty_amount: Decimal | None = None
            duty_source: str | None = None
            duty_breakdown: dict | None = None
            conv_error = False
            if unit_price is not None:
                try:
                    fob = convert(unit_price, quote_ccy, target_ccy, fx_overrides)
                    if row_statutory and duty_fx is not None:
                        # Real Pakistan levy stack on the USD customs value;
                        # duty converted back so comparison stays in target ccy.
                        fob_usd = convert(unit_price, quote_ccy, "USD", fx_overrides)
                        breakdown = compute_duty_stack(
                            hs_code=row_hs,
                            declared_value_usd=fob_usd,
                            exchange_rate=duty_fx,
                            cd_rate=row_resolved["CD"].rate,
                            acd_rate=row_resolved["ACD"].rate,
                            rd_rate=row_resolved["RD"].rate,
                            fed_rate=row_resolved["FED"].rate,
                            st_rate=row_resolved["ST"].rate,
                            wht_rate=row_resolved["WHT_148"].rate,
                            as_of_date=duty_as_of,
                        )
                        duty_usd = breakdown.total_duty_tax_pkr / duty_fx
                        duty_amount = convert(duty_usd, "USD", target_ccy, fx_overrides)
                        landed = (
                            fob
                            + duty_amount
                            + fob * assumptions["lc_pct"]
                            + assumptions["freight_per_unit"]
                        )
                        duty_source = "statutory"
                        duty_breakdown = _duty_breakdown_dict(breakdown, duty_fx)
                    else:
                        landed = landed_unit_cost(
                            fob,
                            duty_pct=assumptions["duty_pct"],
                            freight_per_unit=assumptions["freight_per_unit"],
                            lc_pct=assumptions["lc_pct"],
                        )
                        duty_amount = fob * assumptions["duty_pct"]
                        duty_source = "flat"
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
                "hs_code": row_hs,
                "duty": _num(duty_amount),
                "duty_source": duty_source,
                "duty_breakdown": duty_breakdown,
                "currency": target_ccy,
                "moq": _num(
                    to_decimal(
                        _term(quote.moq, doc_quote.moq if doc_quote else None)
                    )
                ),
                "lead_time_days": _term(
                    quote.lead_time_days,
                    doc_quote.lead_time_days if doc_quote else None,
                ),
                "incoterms": _term(
                    quote.incoterms, doc_quote.incoterms if doc_quote else None
                ),
                "valid_until": _term(
                    quote.valid_until.isoformat() if quote.valid_until else None,
                    doc_quote.valid_until.isoformat()
                    if doc_quote is not None and doc_quote.valid_until
                    else None,
                ),
                "payment_terms": _term(
                    extra.get("payment_terms"), doc_extra.get("payment_terms")
                ),
                "warranty": _term(extra.get("warranty"), doc_extra.get("warranty")),
                "validity_days": _term(
                    extra.get("validity_days"), doc_extra.get("validity_days")
                ),
                "extra_fields": spec_fields,
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
                "hs_code": row_hs,
                "best_supplier_id": best_supplier_id,
                "selected_supplier_id": (
                    str(item.selected_supplier_id)
                    if item.selected_supplier_id
                    else None
                ),
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
            "fx_rate_pkr_usd": _num(duty_fx),
            "fx_rate_source": duty_fx_source,
            "display_rate": (
                float(display_rate)
                if display_rate and display_rate > 0 and target_ccy != "USD"
                else None
            ),
            "duty_as_of": duty_as_of.isoformat() if duty_as_of else None,
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
