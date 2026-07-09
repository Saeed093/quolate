"""Statutory Pakistan duty inside the comparison matrix + BOM HS classification.

Rates seeded here are illustrative fixtures, not verified FBR figures.
Every matrix call passes fx_rate so the live FX fetch is never hit.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal

from app.db.models import DutyTaxRate
from app.db.session import SessionLocal
from app.llm.mock import queue_responses

_EFFECTIVE_FROM = date(2024, 7, 1)
CAMERA = "8525.89.00"
FX = 280.0


def _drain() -> int:
    from app.jobs.worker import drain

    return asyncio.run(drain())


def _seed_camera_rates() -> None:
    async def _run() -> None:
        async with SessionLocal() as session:
            session.add_all(
                [
                    DutyTaxRate(
                        hs_code=CAMERA,
                        levy_type="CD",
                        rate_type="percent",
                        rate_value=Decimal("0.20"),
                        legal_reference="First Schedule, Customs Act 1969",
                        effective_from=_EFFECTIVE_FROM,
                    ),
                    DutyTaxRate(
                        hs_code="*",
                        levy_type="ST",
                        rate_type="percent",
                        rate_value=Decimal("0.18"),
                        legal_reference="Sales Tax Act, 1990",
                        effective_from=_EFFECTIVE_FROM,
                    ),
                ]
            )
            await session.commit()

    asyncio.run(_run())


def _project(auth_client) -> str:
    return auth_client.post("/projects", json={"name": "P"}).json()["id"]


def _add_bom(auth_client, pid: str, part: str, hs_code: str | None = None) -> dict:
    body: dict = {"part_name": part}
    if hs_code:
        body["hs_code"] = hs_code
    return auth_client.post(f"/projects/{pid}/bom", json=body).json()


def _upload_quote(auth_client, pid: str, supplier: str, line_no: int, price: float):
    queue_responses(
        json.dumps(
            {
                "supplier_name": supplier,
                "currency": "USD",
                "fields": [
                    {
                        "bom_line_no": line_no,
                        "field_type": "unit_price",
                        "value_num": price,
                        "currency": "USD",
                        "confidence": 0.95,
                        "source_snippet": f"L{line_no} {price}",
                    }
                ],
            }
        )
    )
    resp = auth_client.post(
        f"/projects/{pid}/documents",
        files=[
            ("files", (f"{supplier}-{line_no}.txt", f"{supplier} {price}".encode(), "text/plain"))
        ],
    )
    assert resp.status_code == 201
    assert _drain() >= 1


def test_statutory_duty_replaces_flat_assumption(auth_client):
    _seed_camera_rates()
    pid = _project(auth_client)
    item = _add_bom(auth_client, pid, "Thermal Camera Module", hs_code=CAMERA)
    _upload_quote(auth_client, pid, "ACME", item["line_no"], 100.0)

    matrix = auth_client.get(
        f"/projects/{pid}/matrix?fx_rate={FX}&duty_pct=0.5"  # flat 50% must be ignored
    ).json()
    assert matrix["assumptions"]["fx_rate_pkr_usd"] == FX
    assert matrix["assumptions"]["fx_rate_source"] == "override"
    assert matrix["assumptions"]["duty_as_of"] is not None

    row = matrix["rows"][0]
    assert row["hs_code"] == CAMERA
    cell = row["cells"][matrix["suppliers"][0]["id"]]
    assert cell["duty_source"] == "statutory"
    assert cell["fob"] == 100.0

    # Hand math: assessed 28000 PKR; CD 20% = 5600; ST 18% of 33600 = 6048;
    # duty total 11648 PKR -> 41.60 USD at 280.
    bd = cell["duty_breakdown"]
    assert bd["fx_rate"] == FX
    assert bd["assessed_value_pkr"] == 28000.0
    assert bd["total_duty_tax_pkr"] == 11648.0
    assert cell["duty"] == 41.6
    assert cell["landed"] == 141.6  # fob + duty (no freight/lc set)
    levies = {l["levy_type"]: l["amount_pkr"] for l in bd["levies"]}
    assert levies["CD"] == 5600.0
    assert levies["ST"] == 6048.0


def test_line_without_hs_code_keeps_flat_duty(auth_client):
    _seed_camera_rates()
    pid = _project(auth_client)
    with_hs = _add_bom(auth_client, pid, "Camera", hs_code=CAMERA)
    without_hs = _add_bom(auth_client, pid, "Lens")
    _upload_quote(auth_client, pid, "ACME", with_hs["line_no"], 100.0)
    _upload_quote(auth_client, pid, "ACME", without_hs["line_no"], 50.0)

    matrix = auth_client.get(
        f"/projects/{pid}/matrix?fx_rate={FX}&duty_pct=0.1"
    ).json()
    sup_id = matrix["suppliers"][0]["id"]
    rows = {r["part_name"]: r for r in matrix["rows"]}

    cam = rows["Camera"]["cells"][sup_id]
    assert cam["duty_source"] == "statutory"
    assert cam["landed"] == 141.6

    lens = rows["Lens"]["cells"][sup_id]
    assert lens["duty_source"] == "flat"
    assert lens["landed"] == 55.0  # 50 * (1 + 0.1)
    assert lens["duty"] == 5.0
    assert lens["duty_breakdown"] is None


def test_hs_code_without_ingested_rates_falls_back_to_flat(auth_client):
    # No rate rows seeded for this code (and no wildcard rows in this test DB).
    pid = _project(auth_client)
    item = _add_bom(auth_client, pid, "Widget", hs_code="1234.56.78")
    _upload_quote(auth_client, pid, "ACME", item["line_no"], 100.0)

    matrix = auth_client.get(
        f"/projects/{pid}/matrix?fx_rate={FX}&duty_pct=0.1"
    ).json()
    cell = matrix["rows"][0]["cells"][matrix["suppliers"][0]["id"]]
    assert cell["duty_source"] == "flat"
    assert cell["landed"] == 110.0


def test_classify_bom_hs_endpoint_and_patch(auth_client):
    pid = _project(auth_client)
    item = _add_bom(auth_client, pid, "Thermal Camera Module 384x288")

    queue_responses(
        json.dumps(
            {
                "product_summary": "Uncooled thermal camera module",
                "candidates": [
                    {
                        "hs_code": CAMERA,
                        "description": "Television cameras etc.",
                        "confidence": 0.85,
                        "reasoning": "Thermal imaging camera module",
                    }
                ],
            }
        )
    )
    resp = auth_client.post(f"/projects/{pid}/bom/{item['id']}/classify-hs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["candidates"][0]["hs_code"] == CAMERA

    # User applies the suggestion via the normal PATCH.
    patched = auth_client.patch(f"/bom/{item['id']}", json={"hs_code": CAMERA})
    assert patched.status_code == 200
    assert patched.json()["hs_code"] == CAMERA
    bom = auth_client.get(f"/projects/{pid}/bom").json()
    assert bom[0]["hs_code"] == CAMERA


def test_classify_bom_hs_404_for_foreign_item(auth_client):
    pid = _project(auth_client)
    other_pid = _project(auth_client)
    item = _add_bom(auth_client, other_pid, "Camera")
    resp = auth_client.post(f"/projects/{pid}/bom/{item['id']}/classify-hs")
    assert resp.status_code == 404
