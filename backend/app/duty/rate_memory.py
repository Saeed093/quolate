"""Prefill and persistence of per-user remembered duty rates per HS code.

The invoice calculator never invents rates: each item's editable rate fields
are prefilled here with a per-levy priority of

    1. the user's own remembered rates (`hs_rate_memory` -- what they last
       confirmed by running a calculation with this HS code),
    2. an approved `duty_tax_rates` row resolved for today (general lookup,
       no importer category/ATL refinement -- the invoice sheet doesn't
       capture those), mapped WHT_148 -> ait; AST has no statutory levy row
       so it never comes from the resolver,
    3. the Excel sheet's defaults (`SHEET_DEFAULT_RATES`).

`sources` reports which tier supplied each value so the UI can hint
"memory" / "approved rate" / "default" next to each field.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HsRateMemory
from app.duty.resolver import resolve_rates
from app.duty.sheet_engine import SHEET_DEFAULT_RATES
from app.matrix.landed_cost import to_decimal

#: Prefill keys that are fractions; fed_amount_pkr is handled separately.
_RATE_KEYS = ("cd", "acd", "rd", "st", "ast", "ait")

#: sheet key -> duty_tax_rates levy type (ast intentionally absent).
_RESOLVER_LEVIES = {
    "cd": "CD",
    "acd": "ACD",
    "rd": "RD",
    "st": "ST",
    "ait": "WHT_148",
}


async def get_rate_prefill(
    session: AsyncSession, *, owner_id: uuid.UUID, hs_code: str
) -> tuple[dict[str, Decimal], dict[str, str]]:
    """Resolve the prefill rates + per-key source tier for one HS code."""
    hs = hs_code.strip()
    remembered: dict = {}
    row = (
        await session.execute(
            select(HsRateMemory).where(
                HsRateMemory.owner_id == owner_id, HsRateMemory.hs_code == hs
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        remembered = row.rates or {}

    resolved = await resolve_rates(
        session,
        hs_code=hs,
        importer_category=None,
        atl_status=None,
        as_of_date=date.today(),
    )

    rates: dict[str, Decimal] = {}
    sources: dict[str, str] = {}
    for key in _RATE_KEYS:
        value = to_decimal(remembered.get(key))
        if value is not None:
            rates[key], sources[key] = value, "memory"
            continue
        levy = _RESOLVER_LEVIES.get(key)
        levy_resolved = resolved.get(levy) if levy else None
        # source_row_id distinguishes a real approved row from the resolver's
        # 0-with-note fallback; percent-only because the sheet math is
        # ad-valorem (a 'fixed' PKR rate would be nonsense as a fraction).
        if (
            levy_resolved is not None
            and levy_resolved.source_row_id is not None
            and levy_resolved.rate_type == "percent"
        ):
            rates[key], sources[key] = levy_resolved.rate, "approved_rate"
            continue
        rates[key], sources[key] = SHEET_DEFAULT_RATES[key], "default"

    fed = to_decimal(remembered.get("fed_amount_pkr"))
    if fed is not None:
        rates["fed_amount_pkr"], sources["fed_amount_pkr"] = fed, "memory"
    else:
        rates["fed_amount_pkr"], sources["fed_amount_pkr"] = Decimal(0), "default"

    return rates, sources


async def remember_rates(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    hs_code: str,
    rates: dict[str, Decimal | float | int | str],
) -> None:
    """Upsert the rates the user just calculated with for this HS code."""
    payload = {
        key: str(value)
        for key, value in rates.items()
        if key in (*_RATE_KEYS, "fed_amount_pkr") and value is not None
    }
    stmt = (
        pg_insert(HsRateMemory)
        .values(owner_id=owner_id, hs_code=hs_code.strip(), rates=payload)
        .on_conflict_do_update(
            constraint="uq_hs_rate_memory_owner_hs",
            # on_conflict_do_update skips column onupdate defaults.
            set_={"rates": payload, "updated_at": func.now()},
        )
    )
    await session.execute(stmt)
