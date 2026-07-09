"""M2 ingestion tests. LLM + OCR are mocked by default."""
from __future__ import annotations

import asyncio
import json

import psycopg
import pytest

from app.ingestion.extract import extract_content
from app.ocr import OcrLine, OcrPage
from tests.conftest import _TEST_DB_URL, _sync_url
from tests.fixtures_gen import (
    image_only_pdf,
    png_price_table,
    text_layer_pdf,
    whatsapp_zip,
    xlsx_price_list,
)


def _fake_ocr(image_bytes, langs=None):
    return OcrPage(
        lines=[
            OcrLine(
                text="Widget A unit price 12.50 USD MOQ 100",
                bbox=[10, 20, 300, 45],
                confidence=0.95,
            )
        ],
        mean_confidence=0.95,
        lang="en",
    )


def _drain() -> int:
    from app.jobs.worker import drain

    return asyncio.run(drain())


# ---------- Stage 1-2: type routing + OCR ----------
def test_pdf_with_text_layer_skips_ocr(monkeypatch):
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        return OcrPage()

    monkeypatch.setattr("app.ocr.run_ocr", boom)
    pdf = text_layer_pdf(
        ["Supplier ACME Co", "Widget A unit price 12.50 USD", "MOQ 100 units"]
    )
    content = extract_content("quote.pdf", "application/pdf", pdf)

    assert content.ocr_used is False
    assert content.kind_detail == "pdf_text"
    assert "Widget A" in content.full_text
    assert calls["n"] == 0


def test_scanned_pdf_triggers_ocr(monkeypatch):
    calls = {"n": 0}

    def fake(image_bytes, langs=None):
        calls["n"] += 1
        return _fake_ocr(image_bytes, langs)

    monkeypatch.setattr("app.ocr.run_ocr", fake)
    pdf = image_only_pdf(["Widget A 12.50 USD", "MOQ 100"])
    content = extract_content("scan.pdf", "application/pdf", pdf)

    assert content.ocr_used is True
    assert content.kind_detail == "pdf_ocr"
    assert calls["n"] >= 1
    assert "Widget A" in content.full_text


def test_xlsx_rows_extracted():
    data = xlsx_price_list(
        [["Part", "Price", "MOQ"], ["Widget A", "12.50", "100"], ["Widget B", "7.00", "50"]]
    )
    content = extract_content(
        "prices.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        data,
    )
    assert "Widget A" in content.full_text
    assert "12.50" in content.full_text
    assert "Widget B" in content.full_text


def test_whatsapp_zip_parses_messages_and_media(monkeypatch):
    monkeypatch.setattr("app.ocr.run_ocr", _fake_ocr)
    chat = (
        "[1/2/2024, 10:00:00] ACME: Widget A is 12.50 USD each\n"
        "[1/2/2024, 10:01:00] Me: what is the MOQ?\n"
        "[1/2/2024, 10:02:00] ACME: MOQ is 100 units\n"
    )
    img = png_price_table(["Widget price list"])
    data = whatsapp_zip(chat, [img])
    content = extract_content("chat.zip", "application/zip", data)

    assert "Widget A is 12.50 USD" in content.full_text
    assert "MOQ is 100 units" in content.full_text
    assert content.page_count >= 2  # chat page + one media page


# ---------- Stage 3: schema enforcement ----------
def test_llm_json_schema_enforced_with_repair_retry():
    from app.llm.json_enforce import complete_json
    from app.llm.mock import MockLLMClient, queue_responses
    from app.llm.prompts import EXTRACTION_SCHEMA

    # First response malformed, second valid -> repair round-trip succeeds.
    queue_responses(
        "sorry, here is the data but not json",
        json.dumps(
            {"fields": [{"field_type": "unit_price", "confidence": 0.9, "value_num": 12.5}]}
        ),
    )
    client = MockLLMClient()
    result = complete_json(
        client, [{"role": "user", "content": "extract"}], EXTRACTION_SCHEMA
    )
    assert result["fields"][0]["field_type"] == "unit_price"


def test_provenance_snippet_fuzzy_match_attaches_page():
    from app.ingestion.provenance import locate_snippet
    from app.ingestion.types import PageContent

    pages = [
        PageContent(
            page_no=3,
            text="",
            ocr_lines=[
                OcrLine("Widget A unit price 12.50 USD", [10, 20, 300, 45], 0.95)
            ],
            ocr_used=True,
        )
    ]
    prov = locate_snippet("Widget A unit price 12.50", pages)
    assert prov["page"] == 3
    assert prov["bbox"] == [10, 20, 300, 45]


# ---------- Stage 4: persistence via full pipeline ----------
def _make_project_with_bom(auth_client) -> str:
    pid = auth_client.post("/projects", json={"name": "P"}).json()["id"]
    auth_client.post(f"/projects/{pid}/bom", json={"part_name": "Widget A"})
    return pid


def test_low_confidence_fields_flag_needs_review(auth_client):
    from app.llm.mock import queue_responses

    pid = _make_project_with_bom(auth_client)
    queue_responses(
        json.dumps(
            {
                "supplier_name": "ACME",
                "currency": "USD",
                "fields": [
                    {
                        "bom_line_no": 1,
                        "field_type": "unit_price",
                        "value_num": 12.5,
                        "confidence": 0.4,
                        "source_snippet": "Widget A 12.50",
                    }
                ],
            }
        )
    )
    up = auth_client.post(
        f"/projects/{pid}/documents",
        files=[("files", ("q.txt", b"Widget A price 12.50 USD", "text/plain"))],
    )
    assert up.status_code == 201
    assert _drain() == 1

    docs = auth_client.get(f"/projects/{pid}/documents").json()
    assert docs[0]["status"] == "needs_review"

    review = auth_client.get(f"/documents/{docs[0]['id']}/review").json()
    assert any(f["field_type"] == "unit_price" for f in review["fields"])


def test_duplicate_upload_dedups_by_sha256(auth_client):
    pid = _make_project_with_bom(auth_client)
    content = b"identical quote content Widget A 12.50"
    auth_client.post(
        f"/projects/{pid}/documents",
        files=[("files", ("a.txt", content, "text/plain"))],
    )
    auth_client.post(
        f"/projects/{pid}/documents",
        files=[("files", ("b.txt", content, "text/plain"))],
    )
    docs = auth_client.get(f"/projects/{pid}/documents").json()
    assert len(docs) == 1


def test_auto_bom_from_quote_when_project_has_no_bom(auth_client):
    from app.llm.mock import queue_responses

    pid = auth_client.post("/projects", json={"name": "Auto BOM"}).json()["id"]
    queue_responses(
        json.dumps(
            {
                "supplier_name": "ACME",
                "currency": "USD",
                "line_items": [
                    {
                        "line_no": 1,
                        "part_name": "Thermal Camera",
                        "quantity": 100,
                        "unit_price": 1150,
                    },
                    {
                        "line_no": 2,
                        "part_name": "Tripod",
                        "quantity": 50,
                        "unit_price": 40,
                    },
                ],
                "fields": [
                    {
                        "bom_line_no": 1,
                        "field_type": "unit_price",
                        "value_num": 1150,
                        "confidence": 0.95,
                        "source_snippet": "Thermal Camera 1150",
                    },
                    {
                        "bom_line_no": 2,
                        "field_type": "unit_price",
                        "value_num": 40,
                        "confidence": 0.95,
                        "source_snippet": "Tripod 40",
                    },
                ],
            }
        )
    )
    up = auth_client.post(
        f"/projects/{pid}/documents",
        files=[
            (
                "files",
                ("quote.txt", b"ACME Thermal Camera 1150 Tripod 40", "text/plain"),
            )
        ],
    )
    assert up.status_code == 201
    assert _drain() == 1

    bom = auth_client.get(f"/projects/{pid}/bom").json()
    assert len(bom) == 2
    names = {row["part_name"] for row in bom}
    assert names == {"Thermal Camera", "Tripod"}

    docs = auth_client.get(f"/projects/{pid}/documents").json()
    assert docs[0]["auto_bom_created"] == 2

    matrix = auth_client.get(f"/projects/{pid}/matrix").json()
    assert matrix["summary"]["lines_total"] == 2
    assert matrix["summary"]["suppliers_total"] == 1


def test_reparse_failed_document(auth_client, monkeypatch):
    from app.ingestion import llm_extract
    from app.llm.mock import queue_responses

    pid = auth_client.post("/projects", json={"name": "Reparse"}).json()["id"]
    attempts = {"n": 0}

    def flaky_extract(bom_lines, full_text):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("LLM offline")
        return llm_extract.extract_fields(bom_lines, full_text)

    monkeypatch.setattr("app.ingestion.pipeline.extract_fields", flaky_extract)
    auth_client.post(
        f"/projects/{pid}/documents",
        files=[("files", ("bad.txt", b"quote body", "text/plain"))],
    )
    assert _drain() == 1
    doc_id = auth_client.get(f"/projects/{pid}/documents").json()[0]["id"]
    assert auth_client.get(f"/projects/{pid}/documents").json()[0]["status"] == "failed"

    queue_responses(
        json.dumps(
            {
                "supplier_name": "ACME",
                "currency": "USD",
                "line_items": [{"line_no": 1, "part_name": "Widget A", "unit_price": 9.5}],
                "fields": [
                    {
                        "bom_line_no": 1,
                        "field_type": "unit_price",
                        "value_num": 9.5,
                        "confidence": 0.95,
                        "source_snippet": "Widget A 9.5",
                    }
                ],
            }
        )
    )
    resp = auth_client.post(f"/documents/{doc_id}/reparse")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
    assert _drain() == 1

    docs = auth_client.get(f"/projects/{pid}/documents").json()
    assert docs[0]["status"] in ("parsed", "needs_review")
    assert len(auth_client.get(f"/projects/{pid}/bom").json()) == 1


def test_reparse_all_requeues_every_parsed_document(auth_client):
    from app.llm.mock import queue_responses

    pid = _make_project_with_bom(auth_client)

    def _resp(supplier: str, price: float) -> str:
        return json.dumps(
            {
                "supplier_name": supplier,
                "currency": "USD",
                "fields": [
                    {
                        "bom_line_no": 1,
                        "field_type": "unit_price",
                        "value_num": price,
                        "confidence": 0.95,
                        "source_snippet": f"Widget A {price}",
                    }
                ],
            }
        )

    queue_responses(_resp("ACME", 12.5))
    auth_client.post(
        f"/projects/{pid}/documents",
        files=[("files", ("a.txt", b"Widget A 12.50 acme", "text/plain"))],
    )
    assert _drain() == 1
    queue_responses(_resp("Globex", 11.0))
    auth_client.post(
        f"/projects/{pid}/documents",
        files=[("files", ("b.txt", b"Widget A 11.00 globex", "text/plain"))],
    )
    assert _drain() == 1

    queue_responses(_resp("ACME", 12.5), _resp("Globex", 11.0))
    resp = auth_client.post(f"/projects/{pid}/documents/reparse-all")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert all(d["status"] == "pending" for d in body)
    assert _drain() == 2

    docs = auth_client.get(f"/projects/{pid}/documents").json()
    assert all(d["status"] in ("parsed", "needs_review") for d in docs)

    # Pressing again while everything is idle re-queues again (no 409s).
    queue_responses(_resp("ACME", 12.5), _resp("Globex", 11.0))
    resp2 = auth_client.post(f"/projects/{pid}/documents/reparse-all")
    assert resp2.status_code == 200
    assert len(resp2.json()) == 2
    assert _drain() == 2


def test_reparse_all_skips_pending_documents(auth_client):
    from app.llm.mock import queue_responses

    pid = _make_project_with_bom(auth_client)
    queue_responses(
        json.dumps({"supplier_name": "ACME", "currency": "USD", "fields": []})
    )
    auth_client.post(
        f"/projects/{pid}/documents",
        files=[("files", ("a.txt", b"quote body", "text/plain"))],
    )
    # Do NOT drain — the document is still pending.
    resp = auth_client.post(f"/projects/{pid}/documents/reparse-all")
    assert resp.status_code == 200
    assert resp.json() == []  # pending doc skipped, no 409


def test_quote_revision_supersedes_previous(auth_client):
    from app.llm.mock import queue_responses

    pid = _make_project_with_bom(auth_client)

    def _resp(price: float) -> str:
        return json.dumps(
            {
                "supplier_name": "ACME",
                "currency": "USD",
                "fields": [
                    {
                        "bom_line_no": 1,
                        "field_type": "unit_price",
                        "value_num": price,
                        "confidence": 0.95,
                        "source_snippet": f"Widget A {price}",
                    }
                ],
            }
        )

    queue_responses(_resp(12.5))
    auth_client.post(
        f"/projects/{pid}/documents",
        files=[("files", ("rev1.txt", b"Widget A 12.50 rev1", "text/plain"))],
    )
    assert _drain() == 1

    queue_responses(_resp(11.0))
    auth_client.post(
        f"/projects/{pid}/documents",
        files=[("files", ("rev2.txt", b"Widget A 11.00 rev2", "text/plain"))],
    )
    assert _drain() == 1

    with psycopg.connect(_sync_url(_TEST_DB_URL)) as conn:
        rows = conn.execute(
            "SELECT unit_price, superseded_by FROM quotes ORDER BY created_at"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0][1] is not None  # first quote superseded
    assert rows[1][1] is None  # latest quote active
