"""Seed a handful of illustrative Pakistan duty/tax rates for local demo use.

These are NOT verified current FBR/SRO figures -- they only exist so the
`/duty-calc` endpoint and the frontend calculator page have something to
show before the real ingestion pipeline (a later session) lands.

Run: python -m app.scripts.seed_duty_rates   (or: .\tasks.ps1 seed-duty)
Idempotent: clears and re-inserts only the rows this script owns (matched
by sro_reference prefix "SEED-DEMO"), so it's safe to re-run.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, or_

from app.db.models import DutyTaxRate, ExemptionRule
from app.db.session import SessionLocal

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_EFFECTIVE_FROM = date(2024, 7, 1)
_TAG = "SEED-DEMO"  # marks rows owned by this script, for idempotent re-runs

MOBILE = "8517.12.00"  # Cellular telephones
CAR = "8703.23.00"  # Motor cars, 1500cc-3000cc
MACHINERY = "8479.89.00"  # Industrial machinery, n.e.s.
LAPTOP = "8471.30.00"  # Portable automatic data processing machines


async def _clear_seed_rows(session) -> None:
    await session.execute(
        delete(DutyTaxRate).where(
            or_(
                DutyTaxRate.sro_reference.ilike(f"{_TAG}%"),
                DutyTaxRate.legal_reference.ilike(f"{_TAG}%"),
            )
        )
    )
    await session.execute(
        delete(ExemptionRule).where(ExemptionRule.sro_reference.ilike(f"{_TAG}%"))
    )


async def _seed() -> None:
    async with SessionLocal() as session:
        await _clear_seed_rows(session)

        # General/wildcard rows (not keyed by HS code).
        session.add_all(
            [
                DutyTaxRate(
                    hs_code="*",
                    levy_type="ST",
                    rate_type="percent",
                    rate_value=Decimal("0.18"),
                    legal_reference="Sales Tax Act, 1990 -- standard rate (s.3)",
                    sro_reference=f"{_TAG}: standard ST rate",
                    effective_from=_EFFECTIVE_FROM,
                ),
                DutyTaxRate(
                    hs_code="*",
                    levy_type="ACD",
                    rate_type="slab",
                    slab_rules=[
                        {"cd_rate_min": 0.0, "cd_rate_max": 0.10, "rate": 0.01},
                        {"cd_rate_min": 0.10, "cd_rate_max": 0.25, "rate": 0.02},
                        {"cd_rate_min": 0.25, "cd_rate_max": None, "rate": 0.06},
                    ],
                    legal_reference="Illustrative ACD slab schedule (demo seed)",
                    sro_reference=f"{_TAG}: ACD slab schedule",
                    effective_from=_EFFECTIVE_FROM,
                ),
                DutyTaxRate(
                    hs_code="*",
                    levy_type="WHT_148",
                    rate_type="percent",
                    rate_value=Decimal("0.01"),
                    atl_status="atl",
                    legal_reference="Income Tax Ordinance, 2001, s.148 -- ATL rate",
                    sro_reference=f"{_TAG}: WHT-148 general ATL rate",
                    effective_from=_EFFECTIVE_FROM,
                ),
                DutyTaxRate(
                    hs_code="*",
                    levy_type="WHT_148",
                    rate_type="percent",
                    rate_value=Decimal("0.02"),
                    atl_status="non_atl",
                    legal_reference="Income Tax Ordinance, 2001, s.148 -- non-ATL rate (~2x)",
                    sro_reference=f"{_TAG}: WHT-148 general non-ATL rate",
                    effective_from=_EFFECTIVE_FROM,
                ),
            ]
        )

        # Mobile phone: HS-specific ACD override (bypasses the slab schedule).
        session.add_all(
            [
                DutyTaxRate(
                    hs_code=MOBILE,
                    levy_type="CD",
                    rate_type="percent",
                    rate_value=Decimal("0.20"),
                    legal_reference="First Schedule, Customs Act 1969",
                    sro_reference=f"{_TAG}: mobile phone CD",
                    effective_from=_EFFECTIVE_FROM,
                ),
                DutyTaxRate(
                    hs_code=MOBILE,
                    levy_type="ACD",
                    rate_type="percent",
                    rate_value=Decimal("0.02"),
                    sro_reference=f"{_TAG}: mobile phone ACD override",
                    effective_from=_EFFECTIVE_FROM,
                ),
            ]
        )

        # Laptop: low CD, no ACD override -> falls back to the slab schedule.
        session.add(
            DutyTaxRate(
                hs_code=LAPTOP,
                levy_type="CD",
                rate_type="percent",
                rate_value=Decimal("0"),
                legal_reference="First Schedule, Customs Act 1969",
                sro_reference=f"{_TAG}: laptop CD",
                notes="Zero-rated under IT equipment concession (demo seed).",
                effective_from=_EFFECTIVE_FROM,
            )
        )

        # Motor car: high CD, RD only because this PCT code is flagged.
        session.add_all(
            [
                DutyTaxRate(
                    hs_code=CAR,
                    levy_type="CD",
                    rate_type="percent",
                    rate_value=Decimal("0.30"),
                    legal_reference="First Schedule, Customs Act 1969",
                    sro_reference=f"{_TAG}: motor car CD",
                    effective_from=_EFFECTIVE_FROM,
                ),
                DutyTaxRate(
                    hs_code=CAR,
                    levy_type="RD",
                    rate_type="percent",
                    rate_value=Decimal("0.15"),
                    sro_reference=f"{_TAG}: motor car RD",
                    effective_from=_EFFECTIVE_FROM,
                ),
            ]
        )

        # Industrial machinery: Eighth-Schedule-style zero ST rate (pure
        # HS-code lookup), plus an importer-category-conditional WHT-148
        # exemption for "own use" imports (exemption_rules, not a flat rate).
        session.add_all(
            [
                DutyTaxRate(
                    hs_code=MACHINERY,
                    levy_type="CD",
                    rate_type="percent",
                    rate_value=Decimal("0.05"),
                    legal_reference="First Schedule, Customs Act 1969",
                    sro_reference=f"{_TAG}: machinery CD",
                    effective_from=_EFFECTIVE_FROM,
                ),
                DutyTaxRate(
                    hs_code=MACHINERY,
                    levy_type="ST",
                    rate_type="percent",
                    rate_value=Decimal("0"),
                    legal_reference="Eighth Schedule, Sales Tax Act 1990",
                    sro_reference=f"{_TAG}: machinery ST zero-rate",
                    notes="Zero-rated plant & machinery item (demo seed).",
                    effective_from=_EFFECTIVE_FROM,
                ),
                ExemptionRule(
                    hs_code=None,
                    levy_type="WHT_148",
                    importer_category="industrial_undertaking_own_use",
                    certificate_type="Industrial Undertaking Exemption Certificate (FBR)",
                    requires_certificate=True,
                    exemption_type="full",
                    condition_description=(
                        "Plant/machinery/equipment imported by an industrial "
                        "undertaking for its own use."
                    ),
                    schedule_reference="Twelfth Schedule condition (demo seed)",
                    sro_reference=f"{_TAG}: WHT-148 industrial undertaking exemption",
                    effective_from=_EFFECTIVE_FROM,
                ),
            ]
        )

        await session.commit()
        print(
            "Seeded illustrative duty/tax rates for: "
            f"{MOBILE} (mobile phone), {LAPTOP} (laptop), {CAR} (motor car), "
            f"{MACHINERY} (industrial machinery)."
        )


if __name__ == "__main__":
    asyncio.run(_seed())
