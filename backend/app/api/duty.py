"""Pakistan duty/tax calculator router.

Only `GET /duty-calc/{hs_code}` for this session -- batch calc and the admin
ingestion/review endpoints come once the core schema + calc logic have been
reviewed (see pakistan-duty-tax-engine-prompt.md).
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db.models import DutyTaxRate, User
from app.db.session import get_session
from app.duty.calculator import calculate_duty
from app.duty.classifier import ClassificationInputError, classify_hs_code
from app.duty.resolver import GENERAL_HS_CODE
from app.duty.schemas import AtlStatus, DutyCalculationOut, HsClassificationOut, LevyLineOut
from app.llm.json_enforce import SchemaEnforceError

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
