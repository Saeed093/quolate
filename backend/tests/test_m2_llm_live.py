"""Live LLM extraction against a running Ollama. Run with: pytest -m llm"""
from __future__ import annotations

import pytest

from tests.fixtures_gen import text_layer_pdf


@pytest.mark.llm
def test_llm_extracts_known_synthetic_quote(monkeypatch):
    from app.config import settings
    from app.ingestion.extract import extract_content
    from app.ingestion.llm_extract import extract_fields

    # Point the client at the real local Ollama for this test only.
    monkeypatch.setattr(settings, "llm_base_url", "http://localhost:11434/v1")
    monkeypatch.setattr(settings, "llm_api_key", "ollama")
    monkeypatch.setattr(settings, "llm_model", "qwen3:8b")

    pdf = text_layer_pdf(
        [
            "Quotation from Shenzhen Widget Co.",
            "Item: Thermal Camera Model TC-640",
            "Unit price: USD 1250.00 per unit",
            "MOQ: 50 units",
            "Lead time: 30 days",
            "Incoterms: FOB Shenzhen",
        ]
    )
    content = extract_content("quote.pdf", "application/pdf", pdf)
    bom_lines = [
        {"line_no": 1, "part_name": "Thermal Camera", "spec_requirement": "640x480", "quantity": 100}
    ]
    result = extract_fields(bom_lines, content.full_text)

    fields = result["fields"]
    assert fields, "model returned no fields"

    prices = [
        f.get("value_num")
        for f in fields
        if f.get("field_type") == "unit_price" and f.get("value_num") is not None
    ]
    assert prices, "no unit_price extracted"
    assert any(abs(float(p) - 1250.0) <= 50 for p in prices)
