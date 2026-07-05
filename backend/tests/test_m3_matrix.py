"""M3 matrix + landed-cost tests. LLM mocked; math is deterministic."""
from __future__ import annotations

import asyncio
import io
import json
from decimal import Decimal

from app.llm.mock import queue_responses
from app.matrix.fx import convert
from app.matrix.landed_cost import landed_unit_cost


def _drain() -> int:
    from app.jobs.worker import drain

    return asyncio.run(drain())


# ---------- Pure math ----------
def test_landed_cost_formula_exact_values():
    # 100 * (1 + 0.10 + 0.05) + 3 = 118
    result = landed_unit_cost(
        Decimal("100"),
        duty_pct=Decimal("0.10"),
        lc_pct=Decimal("0.05"),
        freight_per_unit=Decimal("3"),
    )
    assert result == Decimal("118.00")

    # No add-ons -> equals FOB.
    assert landed_unit_cost(Decimal("50")) == Decimal("50")

    # Coerces plain numbers/strings.
    assert landed_unit_cost("10", duty_pct=0.2, freight_per_unit=1, lc_pct=0) == Decimal(
        "13.0"
    )


def test_currency_conversion_with_manual_override():
    # Override CNY to exactly 7.0 per USD -> 700 CNY == 100 USD.
    usd = convert(Decimal("700"), "CNY", "USD", {"CNY": 7.0})
    assert usd == Decimal("100")

    # Same currency is a no-op.
    assert convert(Decimal("42"), "USD", "USD") == Decimal("42")

    # Bundled static rate still works without an override (EUR 0.92 per USD).
    eur = convert(Decimal("92"), "EUR", "USD")
    assert eur == Decimal("100")


# ---------- Integration helpers ----------
def _project(auth_client, defaults: dict | None = None) -> str:
    body = {"name": "P"}
    if defaults is not None:
        body["landed_cost_defaults"] = defaults
    return auth_client.post("/projects", json=body).json()["id"]


def _add_bom(auth_client, pid: str, part: str) -> int:
    return auth_client.post(f"/projects/{pid}/bom", json={"part_name": part}).json()[
        "line_no"
    ]


def _upload_quote(
    auth_client,
    pid: str,
    *,
    supplier: str,
    line_no: int,
    price: float,
    confidence: float = 0.95,
    currency: str = "USD",
) -> None:
    queue_responses(
        json.dumps(
            {
                "supplier_name": supplier,
                "currency": currency,
                "fields": [
                    {
                        "bom_line_no": line_no,
                        "field_type": "unit_price",
                        "value_num": price,
                        "currency": currency,
                        "confidence": confidence,
                        "source_snippet": f"{supplier} {part_price(line_no, price)}",
                    }
                ],
            }
        )
    )
    fn = f"{supplier}-{line_no}-{price}.txt"
    content = f"{supplier} line {line_no} price {price}".encode()
    resp = auth_client.post(
        f"/projects/{pid}/documents",
        files=[("files", (fn, content, "text/plain"))],
    )
    assert resp.status_code == 201
    assert _drain() >= 1


def part_price(line_no: int, price: float) -> str:
    return f"L{line_no} {price}"


# ---------- Matrix builder ----------
def test_best_value_flag_lowest_landed(auth_client):
    pid = _project(auth_client)
    line = _add_bom(auth_client, pid, "Widget A")
    _upload_quote(auth_client, pid, supplier="ACME", line_no=line, price=12.5)
    _upload_quote(auth_client, pid, supplier="Globex", line_no=line, price=10.0)

    matrix = auth_client.get(f"/projects/{pid}/matrix").json()
    row = matrix["rows"][0]
    suppliers = {s["name"]: s["id"] for s in matrix["suppliers"]}

    globex_cell = row["cells"][suppliers["Globex"]]
    acme_cell = row["cells"][suppliers["ACME"]]
    assert globex_cell["best_value"] is True
    assert acme_cell["best_value"] is False
    assert row["best_supplier_id"] == suppliers["Globex"]


def test_gap_cell_when_supplier_missing_line(auth_client):
    pid = _project(auth_client)
    l1 = _add_bom(auth_client, pid, "Widget A")
    l2 = _add_bom(auth_client, pid, "Widget B")
    # ACME quotes both lines; Globex only line 1.
    _upload_quote(auth_client, pid, supplier="ACME", line_no=l1, price=12.5)
    _upload_quote(auth_client, pid, supplier="ACME", line_no=l2, price=8.0)
    _upload_quote(auth_client, pid, supplier="Globex", line_no=l1, price=10.0)

    matrix = auth_client.get(f"/projects/{pid}/matrix").json()
    suppliers = {s["name"]: s["id"] for s in matrix["suppliers"]}
    line2_row = next(r for r in matrix["rows"] if r["line_no"] == l2)
    globex_cell = line2_row["cells"][suppliers["Globex"]]
    assert globex_cell["confidence_state"] == "gap"
    assert globex_cell["landed"] is None


def test_verify_state_when_any_field_unconfirmed_below_threshold(auth_client):
    pid = _project(auth_client)
    line = _add_bom(auth_client, pid, "Widget A")
    _upload_quote(
        auth_client, pid, supplier="ACME", line_no=line, price=12.5, confidence=0.4
    )

    matrix = auth_client.get(f"/projects/{pid}/matrix").json()
    suppliers = {s["name"]: s["id"] for s in matrix["suppliers"]}
    cell = matrix["rows"][0]["cells"][suppliers["ACME"]]
    assert cell["confidence_state"] == "verify"

    # Confirming the field flips the cell to ok.
    review = auth_client.get(
        f"/documents/{_first_doc(auth_client, pid)}/review"
    ).json()
    field_id = next(f["id"] for f in review["fields"] if f["field_type"] == "unit_price")
    auth_client.patch(f"/fields/{field_id}", json={"status": "confirmed"})

    matrix2 = auth_client.get(f"/projects/{pid}/matrix").json()
    cell2 = matrix2["rows"][0]["cells"][suppliers["ACME"]]
    assert cell2["confidence_state"] == "ok"


def test_export_xlsx_opens_and_matches_matrix(auth_client):
    from openpyxl import load_workbook

    pid = _project(auth_client, defaults={"duty_pct": 0.1, "lc_pct": 0.05, "freight_per_unit": 3})
    line = _add_bom(auth_client, pid, "Widget A")
    _upload_quote(auth_client, pid, supplier="ACME", line_no=line, price=100.0)

    matrix = auth_client.get(f"/projects/{pid}/matrix").json()
    suppliers = {s["name"]: s["id"] for s in matrix["suppliers"]}
    landed = matrix["rows"][0]["cells"][suppliers["ACME"]]["landed"]
    assert landed == 118.0  # 100 * 1.15 + 3

    resp = auth_client.get(f"/projects/{pid}/matrix/export")
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]

    wb = load_workbook(io.BytesIO(resp.content))
    ws = wb["Matrix"]
    header = [c.value for c in ws[1]]
    assert header[0] == "Line"
    assert any("ACME" in str(h) for h in header)
    # Data row: last column is ACME landed.
    data_row = [c.value for c in ws[2]]
    assert data_row[-1] == 118.0


def _first_doc(auth_client, pid: str) -> str:
    docs = auth_client.get(f"/projects/{pid}/documents").json()
    return docs[0]["id"]
