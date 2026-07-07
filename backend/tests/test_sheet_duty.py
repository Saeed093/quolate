"""Sheet-style invoice duty calculator: pure engine, FX, and the
/duty-calc/invoice/* + rate-prefill + fx-rate endpoints.

The reference fixture is the user's actual clearing-agent Excel sheet
("Duty Calculation Sheet"): USD 1,000 invoice @ 278.55 PKR/USD with rates
CD 5% / ACD 2% / RD 15% / ST 18% / AST 3% / AIT 5.5% and the default fee
block. The sheet displays integer-rounded cells; the engine keeps full
precision, so tests assert both the exact quantized values and that they
round to the sheet's displayed figures.
"""
from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.duty.sheet_engine import (
    SHEET_DEFAULT_RATES,
    allocate_freight,
    compute_invoice_sheet_duty,
    compute_item_sheet_duty,
)
from app.matrix import fx_live

FX = Decimal("278.55")


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q0(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


# ---------- Pure math (no DB) ----------
def test_sheet_engine_matches_excel_sample():
    item = compute_item_sheet_duty(
        description="Sample goods",
        hs_code="8479.89.00",
        line_total=Decimal("1000"),
        freight_allocated=Decimal("0"),
        fx_rate=FX,
        rates=SHEET_DEFAULT_RATES,
    )
    assert item.cf_value_pkr == Decimal("278550.00")
    assert _q2(item.insurance_pkr) == Decimal("2785.50")
    assert _q2(item.landing_pkr) == Decimal("2813.36")  # (C&F + insurance) * 1%
    assert _q2(item.import_value_pkr) == Decimal("284148.86")  # sheet: 284,149
    assert _q2(item.line("CD").amount_pkr) == Decimal("14207.44")  # sheet: 14,207
    assert _q2(item.line("ACD").amount_pkr) == Decimal("5682.98")  # sheet: 5,683
    assert _q2(item.line("RD").amount_pkr) == Decimal("42622.33")  # sheet: 42,622
    assert _q2(item.line("ST").basis_pkr) == Decimal("346661.60")
    assert _q2(item.line("ST").amount_pkr) == Decimal("62399.09")  # sheet: 62,399
    # AST on (CD + ACD + RD) only -- the sheet's base, not the statutory one.
    assert _q2(item.line("AST").basis_pkr) == Decimal("62512.75")
    assert _q2(item.line("AST").amount_pkr) == Decimal("1875.38")  # sheet: 1,875
    assert item.line("FED").amount_pkr == Decimal("0")
    assert _q2(item.customs_subtotal_pkr) == Decimal("126787.22")  # sheet: 126,787
    assert _q2(item.line("AIT").basis_pkr) == Decimal("410936.07")
    assert _q2(item.ait_pkr) == Decimal("22601.48")  # sheet: 22,601
    assert _q2(item.item_duty_total_pkr) == Decimal("149388.70")  # sheet: 149,389
    assert _q0(item.item_duty_total_pkr) == Decimal("149389")

    invoice = compute_invoice_sheet_duty(
        items=[
            {
                "description": "Sample goods",
                "hs_code": "8479.89.00",
                "line_total": Decimal("1000"),
                "rates": SHEET_DEFAULT_RATES,
            }
        ],
        currency="USD",
        fx_rate=FX,
    )
    assert _q2(invoice.afu_pkr) == Decimal("2276.19")  # sheet: 2,276
    assert invoice.stamp_fee_pkr == Decimal("2000")
    assert invoice.psw_fee_pkr == Decimal("1000")
    assert _q2(invoice.total_payable_pkr) == Decimal("154664.89")
    assert _q0(invoice.total_payable_pkr) == Decimal("154665")  # sheet: 154,665
    # Landed cleared price = C&F PKR + everything payable.
    assert _q2(invoice.landed_cleared_price_pkr) == Decimal("433214.89")


def test_invoice_freight_prorata_allocation():
    invoice = compute_invoice_sheet_duty(
        items=[
            {"description": "A", "hs_code": "1111.11.11", "line_total": Decimal("600")},
            {"description": "B", "hs_code": "2222.22.22", "line_total": Decimal("400")},
        ],
        currency="USD",
        fx_rate=FX,
        freight=Decimal("100"),
    )
    assert invoice.items[0].freight_allocated == Decimal("60")
    assert invoice.items[1].freight_allocated == Decimal("40")

    # Linearity: with identical rates, two items must together produce the
    # same import value (and duties) as one 1000+100 line.
    single = compute_invoice_sheet_duty(
        items=[
            {"description": "AB", "hs_code": "1111.11.11", "line_total": Decimal("1000")}
        ],
        currency="USD",
        fx_rate=FX,
        freight=Decimal("100"),
    )
    assert _q2(invoice.import_value_pkr) == _q2(single.import_value_pkr)
    assert _q2(invoice.total_payable_pkr) == _q2(single.total_payable_pkr)


def test_zero_line_totals_split_freight_equally():
    assert allocate_freight([Decimal(0), Decimal(0)], Decimal("50")) == [
        Decimal("25"),
        Decimal("25"),
    ]
    assert allocate_freight([Decimal("10"), Decimal("30")], Decimal(0)) == [
        Decimal(0),
        Decimal(0),
    ]


def test_fed_manual_amount_in_subtotal_and_ait_base():
    without_fed = compute_item_sheet_duty(
        description="x",
        hs_code="1111.11.11",
        line_total=Decimal("1000"),
        fx_rate=FX,
    )
    with_fed = compute_item_sheet_duty(
        description="x",
        hs_code="1111.11.11",
        line_total=Decimal("1000"),
        fx_rate=FX,
        fed_amount_pkr=Decimal("5000"),
    )
    # FED is a flat add: subtotal grows by 5000, ST must NOT change...
    assert with_fed.line("ST").amount_pkr == without_fed.line("ST").amount_pkr
    assert (
        with_fed.customs_subtotal_pkr - without_fed.customs_subtotal_pkr
    ) == Decimal("5000")
    # ...but AIT's base includes the subtotal, so AIT grows by 5000 * 5.5%.
    assert (with_fed.ait_pkr - without_fed.ait_pkr) == Decimal("5000") * Decimal(
        "0.055"
    )


def test_sheet_engine_rejects_bad_inputs():
    with pytest.raises(ValueError):
        compute_item_sheet_duty(
            description="x", hs_code="x", line_total="-1", fx_rate=FX
        )
    with pytest.raises(ValueError):
        compute_item_sheet_duty(
            description="x", hs_code="x", line_total="100", fx_rate="0"
        )
    with pytest.raises(ValueError):
        compute_invoice_sheet_duty(items=[], currency="USD", fx_rate=FX)


# ---------- Verbatim amount parsing ----------
def test_amount_candidates_conventions():
    from app.duty.invoice_parse import amount_candidates

    # Unambiguous decimal / grouping forms -> one reading.
    assert amount_candidates("825.00") == [Decimal("825.00")]
    assert amount_candidates("$8,770.00") == [Decimal("8770.00")]
    assert amount_candidates("1.234,56") == [Decimal("1234.56")]  # European
    assert amount_candidates("8.770.000") == [Decimal("8770000")]
    assert amount_candidates("12,345,678") == [Decimal("12345678")]
    assert amount_candidates("30") == [Decimal("30")]
    assert amount_candidates(27.5) == [Decimal("27.5")]
    assert amount_candidates("USD 605.00") == [Decimal("605.00")]
    assert amount_candidates(None) == []
    assert amount_candidates("n/a") == []

    # Single separator + exactly three digits -> both readings, likely first.
    assert amount_candidates("27.500") == [Decimal("27.500"), Decimal("27500")]
    assert amount_candidates("1,500") == [Decimal("1500"), Decimal("1.500")]
    # Comma + dot: rightmost separator is the decimal point.
    assert amount_candidates("$8,770.000") == [Decimal("8770.000")]


def test_resolve_item_amounts_uses_qty_price_total_consistency():
    from app.duty.invoice_parse import resolve_item_amounts

    # The supplier-quotation trap: "$27.500" is 27.50 padded to 3 decimals,
    # proven by 30 x 27.5 = 825.00.
    qty, price, total = resolve_item_amounts("30", "$27.500", "$825.00")
    assert (qty, price, total) == (Decimal("30"), Decimal("27.500"), Decimal("825.00"))

    qty, price, total = resolve_item_amounts("2", "44.000", "88.00")
    assert (price, total) == (Decimal("44.000"), Decimal("88.00"))

    # ...but "1,500" with qty 2 and total 3,000 really is one thousand five hundred.
    qty, price, total = resolve_item_amounts("2", "1,500", "3,000.00")
    assert (price, total) == (Decimal("1500"), Decimal("3000.00"))

    # No consistent combo: most-likely readings stand, total backfilled.
    qty, price, total = resolve_item_amounts("5", "10.00", None)
    assert total == Decimal("50.00")


def test_invoice_parse_verbatim_decimal_notation(auth_client):
    """End-to-end regression for the fiber-quotation bug: 3-decimal FOB
    prices must not come back as thousands (27.500 -> 27500)."""
    from app.llm.mock import queue_responses

    queue_responses(
        json.dumps(
            {
                "invoice_currency": "USD",
                "freight": None,
                "items": [
                    {"description": "Fiber G657A2, roll", "quantity": "30", "unit": "roll", "unit_price": "$27.500", "line_total": "$825.00"},
                    {"description": "Fiber G652D, roll", "quantity": "30", "unit": "roll", "unit_price": "$15.700", "line_total": "$471.00"},
                    {"description": "Winding spool Shaft / Axis", "quantity": "2", "unit": "carton", "unit_price": "$44.000", "line_total": "$88.00"},
                    {"description": "Winding machine -new", "quantity": "1", "unit": "wooden box", "unit_price": "$8,770.000", "line_total": "$8,770.00"},
                    {"description": "Fusion Splicer--AI-9", "quantity": "1", "unit": "carton", "unit_price": "$605.000", "line_total": "$605.00"},
                ],
            }
        )
    )
    resp = auth_client.post("/duty-calc/invoice/parse", json={"text": "QUOTATION ..."})
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    got = [(Decimal(i["unit_price"]), Decimal(i["line_total"])) for i in items]
    assert got == [
        (Decimal("27.500"), Decimal("825.00")),
        (Decimal("15.700"), Decimal("471.00")),
        (Decimal("44.000"), Decimal("88.00")),
        (Decimal("8770.000"), Decimal("8770.00")),
        (Decimal("605.000"), Decimal("605.00")),
    ]


# ---------- Endpoints ----------
def test_invoice_parse_endpoint(auth_client):
    from app.llm.mock import queue_responses

    queue_responses(
        json.dumps(
            {
                "invoice_currency": "cny",
                "freight": 250,
                "items": [
                    {
                        "line_no": 1,
                        "description": "Hydraulic gear pump 40cc",
                        "quantity": 10,
                        "unit": "pcs",
                        "unit_price": 60,
                        "line_total": 600,
                    },
                    {
                        # line_total omitted -> backfilled from qty * unit_price
                        "description": "Pressure relief valve",
                        "quantity": 4,
                        "unit_price": 25.5,
                    },
                    {"description": "   "},  # blank description -> dropped
                ],
            }
        )
    )
    resp = auth_client.post(
        "/duty-calc/invoice/parse", json={"text": "INVOICE ... pump ... valve ..."}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["invoice_currency"] == "CNY"
    assert Decimal(data["freight"]) == Decimal("250")
    assert len(data["items"]) == 2
    assert data["items"][0]["description"] == "Hydraulic gear pump 40cc"
    assert Decimal(data["items"][1]["line_total"]) == Decimal("102")
    assert data["disclaimer"]


def test_invoice_parse_requires_exactly_one_input(auth_client):
    resp = auth_client.post("/duty-calc/invoice/parse", json={})
    assert resp.status_code == 422


def _calc_body(**overrides):
    body = {
        "currency": "USD",
        "fx_rate": "278.55",
        "freight": "0",
        "items": [
            {
                "description": "Sample goods",
                "quantity": "10",
                "unit_price": "100",
                "hs_code": "8479.89.00",
                "rates": {
                    "cd": "0.05",
                    "acd": "0.02",
                    "rd": "0.15",
                    "st": "0.18",
                    "ast": "0.03",
                    "ait": "0.055",
                },
            }
        ],
    }
    body.update(overrides)
    return body


def test_invoice_calculate_and_rate_memory(auth_client):
    resp = auth_client.post("/duty-calc/invoice/calculate", json=_calc_body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # line_total backfilled from quantity * unit_price = 1000 -> Excel sample.
    assert Decimal(data["items"][0]["line_total"]) == Decimal("1000")
    assert _q0(Decimal(data["totals"]["total_payable_pkr"])) == Decimal("154665")
    assert _q2(Decimal(data["totals"]["landed_cleared_price_pkr"])) == Decimal(
        "433214.89"
    )
    levy_types = [l["levy_type"] for l in data["items"][0]["levies"]]
    assert levy_types == ["CD", "ACD", "RD", "ST", "AST", "FED", "AIT"]

    # Rates were remembered for this HS code...
    prefill = auth_client.get("/duty-calc/rate-prefill/8479.89.00")
    assert prefill.status_code == 200
    pdata = prefill.json()
    assert Decimal(pdata["rates"]["rd"]) == Decimal("0.15")
    assert pdata["sources"]["rd"] == "memory"

    # ...and a recalculation with edited rates upserts, not duplicates.
    body = _calc_body()
    body["items"][0]["rates"]["rd"] = "0.10"
    assert auth_client.post("/duty-calc/invoice/calculate", json=body).status_code == 200
    pdata = auth_client.get("/duty-calc/rate-prefill/8479.89.00").json()
    assert Decimal(pdata["rates"]["rd"]) == Decimal("0.10")


def test_invoice_calculate_save_rates_off(auth_client):
    body = _calc_body(save_rates=False)
    assert auth_client.post("/duty-calc/invoice/calculate", json=body).status_code == 200
    pdata = auth_client.get("/duty-calc/rate-prefill/8479.89.00").json()
    assert pdata["sources"]["rd"] == "default"


def test_invoice_calculate_requires_price_info(auth_client):
    body = _calc_body()
    del body["items"][0]["quantity"]
    resp = auth_client.post("/duty-calc/invoice/calculate", json=body)
    assert resp.status_code == 422


def test_rate_prefill_priority(auth_client):
    from datetime import date

    from app.db.models import DutyTaxRate
    from app.db.session import SessionLocal

    async def _seed():
        async with SessionLocal() as session:
            session.add(
                DutyTaxRate(
                    hs_code="8517.12.00",
                    levy_type="CD",
                    rate_type="percent",
                    rate_value=Decimal("0.20"),
                    legal_reference="First Schedule, Customs Act 1969",
                    effective_from=date(2024, 7, 1),
                )
            )
            await session.commit()

    import asyncio

    asyncio.run(_seed())

    pdata = auth_client.get("/duty-calc/rate-prefill/8517.12.00").json()
    assert Decimal(pdata["rates"]["cd"]) == Decimal("0.20")
    assert pdata["sources"]["cd"] == "approved_rate"
    # No AST levy exists in duty_tax_rates -- always memory or default.
    assert pdata["sources"]["ast"] == "default"
    assert Decimal(pdata["rates"]["ast"]) == Decimal("0.03")


# ---------- FX ----------
def test_fx_rate_live_and_cross_rate(auth_client, monkeypatch):
    async def _fake_table():
        return {"PKR": Decimal("280"), "CNY": Decimal("7.0"), "USD": Decimal("1")}

    monkeypatch.setattr(fx_live, "_fetch_usd_table", _fake_table)
    fx_live._CACHE.clear()

    resp = auth_client.get("/duty-calc/fx-rate", params={"currency": "USD"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "live"
    assert Decimal(data["rate"]) == Decimal("280")

    resp = auth_client.get("/duty-calc/fx-rate", params={"currency": "CNY"})
    assert Decimal(resp.json()["rate"]) == Decimal("40")  # 280 / 7


def test_fx_rate_static_fallback(auth_client, monkeypatch):
    async def _boom():
        raise RuntimeError("offline")

    monkeypatch.setattr(fx_live, "_fetch_usd_table", _boom)
    fx_live._CACHE.clear()

    resp = auth_client.get("/duty-calc/fx-rate", params={"currency": "USD"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "static"
    assert Decimal(data["rate"]) > 0  # bundled rates.json value

    resp = auth_client.get("/duty-calc/fx-rate", params={"currency": "EUR"})
    assert resp.status_code == 422  # only USD/CNY supported


def test_fx_rate_requires_auth(client):
    resp = client.get("/duty-calc/fx-rate", params={"currency": "USD"})
    assert resp.status_code in (401, 403)
