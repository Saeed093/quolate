"""Top-level async orchestration: DB rate resolution + pure calculation.

This is what API endpoints (and, later, batch/tender-comparison callers)
should call -- `resolve_rates` (DB) feeds straight into `compute_duty_stack`
(pure), so the arithmetic itself never touches the database.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.duty.engine import DutyBreakdown, compute_duty_stack
from app.duty.resolver import resolve_rates


async def calculate_duty(
    session: AsyncSession,
    *,
    hs_code: str,
    declared_value_usd: Decimal | float | int | str,
    exchange_rate: Decimal | float | int | str,
    importer_category: str | None = None,
    atl_status: str | None = None,
    as_of_date: date | None = None,
) -> DutyBreakdown:
    as_of = as_of_date or date.today()
    hs_code_norm = hs_code.strip()

    resolved = await resolve_rates(
        session,
        hs_code=hs_code_norm,
        importer_category=importer_category,
        atl_status=atl_status,
        as_of_date=as_of,
    )
    references = {levy: r.as_reference() for levy, r in resolved.items()}

    return compute_duty_stack(
        hs_code=hs_code_norm,
        declared_value_usd=declared_value_usd,
        exchange_rate=exchange_rate,
        cd_rate=resolved["CD"].rate,
        acd_rate=resolved["ACD"].rate,
        rd_rate=resolved["RD"].rate,
        fed_rate=resolved["FED"].rate,
        st_rate=resolved["ST"].rate,
        wht_rate=resolved["WHT_148"].rate,
        importer_category=importer_category,
        atl_status=atl_status,
        as_of_date=as_of,
        references=references,
    )
