"""Pakistan duty/tax engine: pure calc, DB-backed resolution, and the
GET /duty-calc/{hs_code} endpoint.

Rates seeded below are illustrative fixtures for exercising the engine --
NOT verified current FBR/SRO figures. Real rates land via the (later)
ingestion pipeline.
"""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

from app.db.models import DutyTaxRate, ExemptionRule
from app.db.session import SessionLocal
from app.duty.calculator import calculate_duty
from app.duty.engine import compute_duty_stack

_EFFECTIVE_FROM = date(2024, 7, 1)
_AS_OF = date(2026, 1, 1)

MOBILE = "8517.12.00"
CAR = "8703.23.00"
MACHINERY = "8479.89.00"
VERSIONED = "9999.99.99"
PENDING = "8888.88.88"


# ---------- Pure math (no DB) ----------
def test_compute_duty_stack_exact_compounding_order():
    """1000 USD @ 280 PKR/USD, CD 20%, ACD 2%, ST 18%, WHT 1% -- hand-verified."""
    breakdown = compute_duty_stack(
        hs_code=MOBILE,
        declared_value_usd=Decimal("1000"),
        exchange_rate=Decimal("280"),
        cd_rate=Decimal("0.20"),
        acd_rate=Decimal("0.02"),
        st_rate=Decimal("0.18"),
        wht_rate=Decimal("0.01"),
    )
    assert breakdown.assessed_value_pkr == Decimal("280000")
    assert breakdown.line("CD").amount_pkr == Decimal("56000")
    assert breakdown.line("ACD").amount_pkr == Decimal("5600")
    assert breakdown.line("RD").amount_pkr == Decimal("0")
    # ST is levied on assessed value + CD + ACD + RD + FED, not on assessed alone.
    assert breakdown.line("ST").basis_pkr == Decimal("341600")
    assert breakdown.line("ST").amount_pkr == Decimal("61488")
    # WHT is levied on value_for_st + ST, not on assessed value.
    assert breakdown.line("WHT_148").basis_pkr == Decimal("403088")
    assert breakdown.line("WHT_148").amount_pkr == Decimal("4030.88")
    assert breakdown.total_duty_tax_pkr == Decimal("127118.88")
    assert breakdown.total_landed_pkr == Decimal("407118.88")


def test_compute_duty_stack_zero_rates_is_a_noop():
    breakdown = compute_duty_stack(
        hs_code="0000.00.00", declared_value_usd="500", exchange_rate="280"
    )
    assert breakdown.assessed_value_pkr == Decimal("140000")
    assert breakdown.total_duty_tax_pkr == Decimal("0")
    assert breakdown.total_landed_pkr == Decimal("140000")


def test_compute_duty_stack_rejects_bad_inputs():
    import pytest

    with pytest.raises(ValueError):
        compute_duty_stack(hs_code="x", declared_value_usd="-1", exchange_rate="280")
    with pytest.raises(ValueError):
        compute_duty_stack(hs_code="x", declared_value_usd="100", exchange_rate="0")


# ---------- DB-backed rate resolution ----------
async def _seed_common(session):
    session.add_all(
        [
            DutyTaxRate(
                hs_code="*",
                levy_type="ST",
                rate_type="percent",
                rate_value=Decimal("0.18"),
                legal_reference="Sales Tax Act, 1990",
                sro_reference="Standard rate, s.3",
                effective_from=_EFFECTIVE_FROM,
            ),
            DutyTaxRate(
                hs_code="*",
                levy_type="ACD",
                rate_type="slab",
                slab_rules=[
                    {
                        "cd_rate_min": 0.0,
                        "cd_rate_max": 0.10,
                        "rate": 0.01,
                        "sro_reference": "SRO TEST-ACD/2024",
                    },
                    {
                        "cd_rate_min": 0.10,
                        "cd_rate_max": 0.25,
                        "rate": 0.02,
                        "sro_reference": "SRO TEST-ACD/2024",
                    },
                    {
                        "cd_rate_min": 0.25,
                        "cd_rate_max": None,
                        "rate": 0.03,
                        "sro_reference": "SRO TEST-ACD/2024",
                    },
                ],
                legal_reference="Illustrative ACD slab schedule (test fixture)",
                effective_from=_EFFECTIVE_FROM,
            ),
            DutyTaxRate(
                hs_code="*",
                levy_type="WHT_148",
                rate_type="percent",
                rate_value=Decimal("0.01"),
                atl_status="atl",
                legal_reference="Income Tax Ordinance, 2001, s.148",
                effective_from=_EFFECTIVE_FROM,
            ),
            DutyTaxRate(
                hs_code="*",
                levy_type="WHT_148",
                rate_type="percent",
                rate_value=Decimal("0.02"),
                atl_status="non_atl",
                legal_reference="Income Tax Ordinance, 2001, s.148",
                effective_from=_EFFECTIVE_FROM,
            ),
        ]
    )
    await session.flush()


async def _seed_mobile(session):
    session.add_all(
        [
            DutyTaxRate(
                hs_code=MOBILE,
                levy_type="CD",
                rate_type="percent",
                rate_value=Decimal("0.20"),
                legal_reference="First Schedule, Customs Act 1969",
                effective_from=_EFFECTIVE_FROM,
            ),
            # HS-specific ACD override -- takes precedence over the slab schedule.
            DutyTaxRate(
                hs_code=MOBILE,
                levy_type="ACD",
                rate_type="percent",
                rate_value=Decimal("0.02"),
                sro_reference="SRO TEST-ACD-MOBILE/2024",
                effective_from=_EFFECTIVE_FROM,
            ),
        ]
    )
    await session.flush()


async def _seed_car(session):
    session.add_all(
        [
            DutyTaxRate(
                hs_code=CAR,
                levy_type="CD",
                rate_type="percent",
                rate_value=Decimal("0.30"),
                legal_reference="First Schedule, Customs Act 1969",
                effective_from=_EFFECTIVE_FROM,
            ),
            # RD only applies because this PCT code is explicitly flagged.
            DutyTaxRate(
                hs_code=CAR,
                levy_type="RD",
                rate_type="percent",
                rate_value=Decimal("0.15"),
                sro_reference="SRO TEST-RD-CARS/2024",
                effective_from=_EFFECTIVE_FROM,
            ),
        ]
    )
    await session.flush()


async def _seed_machinery(session):
    session.add_all(
        [
            DutyTaxRate(
                hs_code=MACHINERY,
                levy_type="CD",
                rate_type="percent",
                rate_value=Decimal("0.05"),
                legal_reference="First Schedule, Customs Act 1969",
                effective_from=_EFFECTIVE_FROM,
            ),
            # Eighth-Schedule-style zero rate -- a pure HS-code lookup, so it
            # lives in duty_tax_rates rather than exemption_rules.
            DutyTaxRate(
                hs_code=MACHINERY,
                levy_type="ST",
                rate_type="percent",
                rate_value=Decimal("0"),
                legal_reference="Eighth Schedule, Sales Tax Act 1990",
                notes="Zero-rated plant & machinery item (test fixture).",
                effective_from=_EFFECTIVE_FROM,
            ),
            # Importer-category-conditional WHT-148 exemption -- this is
            # exactly the case exemption_rules exists for.
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
                schedule_reference="Twelfth Schedule condition (test fixture)",
                effective_from=_EFFECTIVE_FROM,
            ),
        ]
    )
    await session.flush()


async def test_mobile_phone_general_case():
    async with SessionLocal() as session:
        await _seed_common(session)
        await _seed_mobile(session)
        await session.commit()

        breakdown = await calculate_duty(
            session,
            hs_code=MOBILE,
            declared_value_usd=Decimal("1000"),
            exchange_rate=Decimal("280"),
            importer_category="commercial_importer",
            atl_status="atl",
            as_of_date=_AS_OF,
        )

    assert breakdown.line("CD").rate == Decimal("0.20")
    assert breakdown.line("ACD").rate == Decimal("0.02")
    assert breakdown.line("ACD").sro_reference == "SRO TEST-ACD-MOBILE/2024"
    assert breakdown.line("RD").rate == Decimal("0")
    assert breakdown.line("ST").rate == Decimal("0.18")
    assert breakdown.line("WHT_148").rate == Decimal("0.01")
    assert breakdown.total_landed_pkr == Decimal("407118.88")


async def test_mobile_phone_non_atl_pays_roughly_double_wht():
    async with SessionLocal() as session:
        await _seed_common(session)
        await _seed_mobile(session)
        await session.commit()

        atl = await calculate_duty(
            session,
            hs_code=MOBILE,
            declared_value_usd=Decimal("1000"),
            exchange_rate=Decimal("280"),
            atl_status="atl",
            as_of_date=_AS_OF,
        )
        non_atl = await calculate_duty(
            session,
            hs_code=MOBILE,
            declared_value_usd=Decimal("1000"),
            exchange_rate=Decimal("280"),
            atl_status="non_atl",
            as_of_date=_AS_OF,
        )

    assert atl.line("WHT_148").rate == Decimal("0.01")
    assert non_atl.line("WHT_148").rate == Decimal("0.02")
    assert non_atl.line("WHT_148").amount_pkr == atl.line("WHT_148").amount_pkr * 2
    assert non_atl.total_landed_pkr > atl.total_landed_pkr


async def test_car_acd_falls_back_to_slab_and_rd_is_hs_specific():
    async with SessionLocal() as session:
        await _seed_common(session)
        await _seed_car(session)
        await session.commit()

        breakdown = await calculate_duty(
            session,
            hs_code=CAR,
            declared_value_usd=Decimal("1000"),
            exchange_rate=Decimal("280"),
            atl_status="atl",
            as_of_date=_AS_OF,
        )

    assert breakdown.line("CD").rate == Decimal("0.30")
    # No HS-specific ACD row -> resolved via the CD-rate-bracket slab (30% -> top bracket).
    acd = breakdown.line("ACD")
    assert acd.rate == Decimal("0.03")
    assert acd.notes and "slab" in acd.notes.lower()
    assert breakdown.line("RD").rate == Decimal("0.15")
    assert breakdown.line("RD").sro_reference == "SRO TEST-RD-CARS/2024"
    assert breakdown.total_landed_pkr == Decimal("493881.92")


async def test_machinery_industrial_undertaking_exemption_vs_commercial_importer():
    async with SessionLocal() as session:
        await _seed_common(session)
        await _seed_machinery(session)
        await session.commit()

        exempt = await calculate_duty(
            session,
            hs_code=MACHINERY,
            declared_value_usd=Decimal("1000"),
            exchange_rate=Decimal("280"),
            importer_category="industrial_undertaking_own_use",
            atl_status="atl",
            as_of_date=_AS_OF,
        )
        commercial = await calculate_duty(
            session,
            hs_code=MACHINERY,
            declared_value_usd=Decimal("1000"),
            exchange_rate=Decimal("280"),
            importer_category="commercial_importer",
            atl_status="atl",
            as_of_date=_AS_OF,
        )

    # Sales Tax exemption is a pure HS-code lookup (Eighth Schedule) -> zero
    # for BOTH importer categories.
    assert exempt.line("ST").rate == Decimal("0")
    assert commercial.line("ST").rate == Decimal("0")

    # WHT-148 exemption is importer-category-conditional (exemption_rules).
    wht_exempt = exempt.line("WHT_148")
    assert wht_exempt.rate == Decimal("0")
    assert wht_exempt.exemption_applied is True
    assert "certificate" in (wht_exempt.notes or "").lower()

    wht_commercial = commercial.line("WHT_148")
    assert wht_commercial.exemption_applied is False
    assert wht_commercial.rate == Decimal("0.01")  # falls back to the general ATL rate

    assert exempt.total_landed_pkr < commercial.total_landed_pkr


async def test_rate_versioning_is_reproducible_for_past_dates():
    """A superseded rate must still be resolvable for an as_of_date in its
    own effective window, so an old quote/calculation stays reproducible."""
    async with SessionLocal() as session:
        old = DutyTaxRate(
            hs_code=VERSIONED,
            levy_type="CD",
            rate_type="percent",
            rate_value=Decimal("0.10"),
            legal_reference="First Schedule (2020 rate)",
            effective_from=date(2020, 1, 1),
            effective_to=date(2023, 6, 30),
        )
        session.add(old)
        await session.flush()
        new = DutyTaxRate(
            hs_code=VERSIONED,
            levy_type="CD",
            rate_type="percent",
            rate_value=Decimal("0.15"),
            legal_reference="First Schedule (2023 Finance Act rate)",
            effective_from=date(2023, 7, 1),
            effective_to=None,
        )
        session.add(new)
        await session.flush()
        old.superseded_by = new.id
        await session.commit()

        before = await calculate_duty(
            session,
            hs_code=VERSIONED,
            declared_value_usd=Decimal("100"),
            exchange_rate=Decimal("100"),
            as_of_date=date(2022, 1, 1),
        )
        after = await calculate_duty(
            session,
            hs_code=VERSIONED,
            declared_value_usd=Decimal("100"),
            exchange_rate=Decimal("100"),
            as_of_date=date(2024, 1, 1),
        )

    assert before.line("CD").rate == Decimal("0.10")
    assert after.line("CD").rate == Decimal("0.15")


async def test_pending_review_rate_is_never_used():
    """LLM-extracted / unapproved rows must never be auto-published."""
    async with SessionLocal() as session:
        session.add(
            DutyTaxRate(
                hs_code=PENDING,
                levy_type="CD",
                rate_type="percent",
                rate_value=Decimal("0.99"),
                status="pending_review",
                effective_from=_EFFECTIVE_FROM,
            )
        )
        await session.commit()

        breakdown = await calculate_duty(
            session,
            hs_code=PENDING,
            declared_value_usd=Decimal("100"),
            exchange_rate=Decimal("100"),
            as_of_date=_AS_OF,
        )

    assert breakdown.line("CD").rate == Decimal("0")
    assert "no cd" in (breakdown.line("CD").notes or "").lower()


# ---------- API endpoint ----------
def test_duty_calc_endpoint(auth_client):
    async def _seed():
        async with SessionLocal() as session:
            await _seed_common(session)
            await _seed_mobile(session)
            await session.commit()

    asyncio.run(_seed())

    resp = auth_client.get(
        f"/duty-calc/{MOBILE}",
        params={
            "declared_value_usd": "1000",
            "exchange_rate": "280",
            "importer_category": "commercial_importer",
            "atl_status": "atl",
            "as_of_date": "2026-01-01",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["hs_code"] == MOBILE
    assert Decimal(body["total_landed_pkr"]) == Decimal("407118.88")
    assert Decimal(body["assessed_value_pkr"]) == Decimal("280000")
    assert body["disclaimer"]
    levy_types = {l["levy_type"] for l in body["levies"]}
    assert levy_types == {"CD", "ACD", "RD", "FED", "ST", "WHT_148"}
    cd_line = next(l for l in body["levies"] if l["levy_type"] == "CD")
    assert Decimal(cd_line["rate"]) == Decimal("0.20")
    assert cd_line["legal_reference"] == "First Schedule, Customs Act 1969"


def test_duty_calc_endpoint_requires_auth(client):
    resp = client.get(
        f"/duty-calc/{MOBILE}",
        params={"declared_value_usd": "1000", "exchange_rate": "280"},
    )
    assert resp.status_code == 401


def test_duty_calc_endpoint_rejects_non_positive_value(auth_client):
    resp = auth_client.get(
        f"/duty-calc/{MOBILE}",
        params={"declared_value_usd": "-5", "exchange_rate": "280"},
    )
    assert resp.status_code == 422


def test_hs_codes_endpoint_lists_known_codes_and_filters(auth_client):
    async def _seed():
        async with SessionLocal() as session:
            await _seed_common(session)
            await _seed_mobile(session)
            await _seed_car(session)
            await session.commit()

    asyncio.run(_seed())

    all_codes = auth_client.get("/duty-calc/hs-codes").json()
    assert MOBILE in all_codes
    assert CAR in all_codes
    assert "*" not in all_codes  # wildcard row is internal, never surfaced

    filtered = auth_client.get("/duty-calc/hs-codes", params={"q": "8517"}).json()
    assert filtered == [MOBILE]
