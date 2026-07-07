"""Pakistan duty/tax calculator router.

Two calculation styles live side by side:
  - `GET /duty-calc/{hs_code}`: the original single-item statutory stack
    (DB-resolved rates via `app.duty.calculator`).
  - `POST /duty-calc/invoice/*`: the clearing-agent sheet workflow -- parse an
    invoice into line items (LLM), then batch-calculate the sheet's duty
    stack per item with client-confirmed rates (pure math, no LLM).
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.models import DutyTaxRate, User
from app.db.session import get_session
from app.duty import rate_memory
from app.duty.calculator import calculate_duty
from app.duty.classifier import ClassificationInputError, classify_hs_code
from app.duty.invoice_parse import parse_invoice_items
from app.duty.resolver import GENERAL_HS_CODE
from app.duty.schemas import (
    AtlStatus,
    DutyCalculationOut,
    FxRateOut,
    HsClassificationOut,
    InvoiceCalcIn,
    InvoiceCalcItemOut,
    InvoiceCalcOut,
    InvoiceParseOut,
    InvoiceTotalsOut,
    LevyLineOut,
    RatePrefillOut,
    SheetLevyLineOut,
)
from app.duty.sheet_engine import compute_invoice_sheet_duty
from app.llm.json_enforce import SchemaEnforceError
from app.matrix.fx_live import get_pkr_rate

router = APIRouter(tags=["duty"])


class ClassifyRequest(BaseModel):
    library_document_id: uuid.UUID | None = None
    text: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "ClassifyRequest":
        has_doc = self.library_document_id is not None
        has_text = bool(self.text and self.text.strip())
        if has_doc == has_text:  # both or neither
            raise ValueError("Provide exactly one of 'library_document_id' or 'text'.")
        return self


@router.get("/duty-calc/hs-codes")
async def list_duty_hs_codes(
    q: str | None = Query(None, description="Filter substring, e.g. '8517'"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[str]:
    """Distinct HS codes with at least one approved rate row -- backs the
    calculator page's autocomplete. Empty until rates are ingested/seeded.
    """
    stmt = (
        select(DutyTaxRate.hs_code)
        .where(DutyTaxRate.hs_code != GENERAL_HS_CODE, DutyTaxRate.status == "approved")
        .distinct()
        .order_by(DutyTaxRate.hs_code)
    )
    if q:
        stmt = stmt.where(DutyTaxRate.hs_code.ilike(f"%{q}%"))
    result = await session.execute(stmt.limit(50))
    return list(result.scalars().all())


# NOTE: declared before `GET /duty-calc/{hs_code}` -- FastAPI matches routes
# in declaration order and the path-param route would swallow this one.
@router.get("/duty-calc/fx-rate", response_model=FxRateOut)
async def get_fx_rate(
    currency: Literal["USD", "CNY"] = Query(...),
    user: User = Depends(get_current_user),
) -> FxRateOut:
    """Today's PKR rate for the invoice calculator (live, static fallback).

    Open-market, not the FBR customs-notified rate -- the UI labels the
    source and keeps the field editable.
    """
    fx = await get_pkr_rate(currency)
    return FxRateOut(
        currency=fx.currency, rate=fx.rate, as_of_date=fx.as_of_date, source=fx.source
    )


@router.get("/duty-calc/rate-prefill/{hs_code}", response_model=RatePrefillOut)
async def get_rate_prefill(
    hs_code: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RatePrefillOut:
    """Editable-rate prefill for one HS code: the user's remembered rates,
    else an approved `duty_tax_rates` row, else the sheet defaults."""
    rates, sources = await rate_memory.get_rate_prefill(
        session, owner_id=user.id, hs_code=hs_code
    )
    return RatePrefillOut(hs_code=hs_code.strip(), rates=rates, sources=sources)


@router.get("/duty-calc/{hs_code}", response_model=DutyCalculationOut)
async def get_duty_calc(
    hs_code: str,
    declared_value_usd: Decimal = Query(
        ..., gt=0, description="Customs-declared value in USD"
    ),
    exchange_rate: Decimal = Query(
        ..., gt=0, description="Customs-notified PKR-per-USD exchange rate"
    ),
    importer_category: str | None = Query(
        None,
        description=(
            "e.g. industrial_undertaking_own_use, commercial_importer. "
            "Null uses the general/default rate for each levy."
        ),
    ),
    atl_status: AtlStatus | None = Query(
        None, description="'atl' or 'non_atl' -- affects the Section 148 rate."
    ),
    as_of_date: date | None = Query(None, description="Defaults to today."),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DutyCalculationOut:
    breakdown = await calculate_duty(
        session,
        hs_code=hs_code,
        declared_value_usd=declared_value_usd,
        exchange_rate=exchange_rate,
        importer_category=importer_category,
        atl_status=atl_status,
        as_of_date=as_of_date,
    )
    return DutyCalculationOut(
        hs_code=breakdown.hs_code,
        declared_value_usd=breakdown.declared_value_usd,
        exchange_rate=breakdown.exchange_rate,
        assessed_value_pkr=breakdown.assessed_value_pkr,
        importer_category=breakdown.importer_category,
        atl_status=breakdown.atl_status,
        as_of_date=breakdown.as_of_date,
        levies=[
            LevyLineOut(
                levy_type=l.levy_type,
                label=l.label,
                rate=l.rate,
                rate_type=l.rate_type,
                basis_pkr=l.basis_pkr,
                amount_pkr=l.amount_pkr,
                legal_reference=l.legal_reference,
                sro_reference=l.sro_reference,
                exemption_applied=l.exemption_applied,
                notes=l.notes,
            )
            for l in breakdown.lines
        ],
        total_duty_tax_pkr=breakdown.total_duty_tax_pkr,
        total_landed_pkr=breakdown.total_landed_pkr,
    )


@router.post("/duty-calc/classify", response_model=HsClassificationOut)
async def classify_duty_hs_code(
    body: ClassifyRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> HsClassificationOut:
    """Suggest candidate HS codes from free text or an uploaded/library document.

    Heuristic, LLM-based suggestions only -- the user still picks and reviews
    a candidate before calculating (see `HsClassificationOut.disclaimer`).
    """
    try:
        return await classify_hs_code(
            session,
            text=body.text,
            library_document_id=body.library_document_id,
            owner_id=user.id,
        )
    except ClassificationInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SchemaEnforceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/duty-calc/invoice/parse", response_model=InvoiceParseOut)
async def parse_invoice(
    body: ClassifyRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> InvoiceParseOut:
    """Extract line items (+ currency/freight) from an invoice or quotation.

    One LLM call; per-item HS classification is a separate follow-up via
    `POST /duty-calc/classify` with each item's description as `text`.
    """
    try:
        return await parse_invoice_items(
            session,
            text=body.text,
            library_document_id=body.library_document_id,
            owner_id=user.id,
        )
    except ClassificationInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SchemaEnforceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/duty-calc/invoice/calculate", response_model=InvoiceCalcOut)
async def calculate_invoice(
    body: InvoiceCalcIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> InvoiceCalcOut:
    """Batch sheet-style duty calculation -- pure math, no LLM.

    Rates arrive from the client exactly as the user confirmed them; when
    `save_rates` is set they are remembered per HS code for future prefill.
    """
    breakdown = compute_invoice_sheet_duty(
        items=[
            {
                "description": item.description,
                "hs_code": item.hs_code,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.line_total,
                "rates": item.rates.model_dump(),
                "fed_amount_pkr": item.fed_amount_pkr,
            }
            for item in body.items
        ],
        currency=body.currency,
        fx_rate=body.fx_rate,
        freight=body.freight,
        insurance_pct=body.insurance_pct,
        landing_pct=body.landing_pct,
        afu_pct=body.fees.afu_pct,
        afu_fixed_pkr=body.fees.afu_fixed_pkr,
        stamp_fee_pkr=body.fees.stamp_fee_pkr,
        psw_fee_pkr=body.fees.psw_fee_pkr,
    )

    if body.save_rates:
        # Dedupe by HS code; the last item's rates win.
        by_hs = {
            item.hs_code.strip(): {
                **item.rates.model_dump(),
                "fed_amount_pkr": item.fed_amount_pkr,
            }
            for item in body.items
        }
        for hs_code, rates in by_hs.items():
            await rate_memory.remember_rates(
                session, owner_id=user.id, hs_code=hs_code, rates=rates
            )
        await session.commit()

    return InvoiceCalcOut(
        currency=breakdown.currency,
        fx_rate=breakdown.fx_rate,
        fx_rate_date=body.fx_rate_date,
        items=[
            InvoiceCalcItemOut(
                description=item.description,
                hs_code=item.hs_code,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
                freight_allocated=item.freight_allocated,
                cf_value=item.cf_value,
                cf_value_pkr=item.cf_value_pkr,
                insurance_pkr=item.insurance_pkr,
                landing_pkr=item.landing_pkr,
                import_value_pkr=item.import_value_pkr,
                levies=[
                    SheetLevyLineOut(
                        levy_type=line.levy_type,
                        label=line.label,
                        rate=line.rate,
                        basis_pkr=line.basis_pkr,
                        amount_pkr=line.amount_pkr,
                    )
                    for line in item.lines
                ],
                customs_subtotal_pkr=item.customs_subtotal_pkr,
                ait_pkr=item.ait_pkr,
                item_duty_total_pkr=item.item_duty_total_pkr,
            )
            for item in breakdown.items
        ],
        totals=InvoiceTotalsOut(
            invoice_value=breakdown.invoice_value,
            freight=breakdown.freight,
            cf_value_pkr=breakdown.cf_value_pkr,
            import_value_pkr=breakdown.import_value_pkr,
            customs_subtotal_pkr=breakdown.customs_subtotal_pkr,
            ait_pkr=breakdown.ait_pkr,
            customs_total_pkr=breakdown.customs_total_pkr,
            afu_pkr=breakdown.afu_pkr,
            stamp_fee_pkr=breakdown.stamp_fee_pkr,
            psw_fee_pkr=breakdown.psw_fee_pkr,
            total_payable_pkr=breakdown.total_payable_pkr,
            landed_cleared_price_pkr=breakdown.landed_cleared_price_pkr,
        ),
    )
