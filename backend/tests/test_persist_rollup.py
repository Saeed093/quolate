"""Unit tests for quote rollup helpers in persist."""
from __future__ import annotations

import uuid

from app.ingestion.persist import (
    _match_bom_by_name,
    _parse_number_from_text,
    _synthesize_fields_from_line_items,
)


def test_parse_number_from_text():
    assert float(_parse_number_from_text("$158.90 USD")) == 158.90
    assert float(_parse_number_from_text("1,250.00")) == 1250.00
    assert _parse_number_from_text("no price") is None


def test_match_bom_by_name_exact_and_fuzzy():
    cam = uuid.uuid4()
    lens = uuid.uuid4()
    names = {
        cam: "Uncooled Microbolometer Thermal Camera Module, 384x288, 12um",
        lens: "Athermalized Thermal Lens Assembly 25mm f/1.0",
    }
    assert _match_bom_by_name("Thermal Camera Module 384x288", names) == cam
    assert _match_bom_by_name("Athermalized Thermal Lens 25mm", names) == lens
    assert _match_bom_by_name("unrelated widget", names) is None


def test_synthesize_fields_from_line_items_fills_missing_prices():
    cam = uuid.uuid4()
    lens = uuid.uuid4()
    line_to_item = {1: cam, 2: lens}
    bom_names = {
        cam: "Uncooled Microbolometer Thermal Camera Module",
        lens: "Athermalized Thermal Lens Assembly",
    }
    extraction = {
        "currency": "USD",
        "line_items": [
            {"line_no": 1, "part_name": "Camera Module", "unit_price": 149.3},
            {"line_no": 2, "part_name": "Lens Assembly", "unit_price": 37.8},
        ],
        # Model returned MOQ/lead time but forgot unit_price fields.
        "fields": [
            {"bom_line_no": 1, "field_type": "moq", "value_num": 50, "confidence": 0.9},
        ],
    }
    extra = _synthesize_fields_from_line_items(extraction, line_to_item, bom_names)
    assert len(extra) == 2
    by_line = {f["bom_line_no"]: f for f in extra}
    assert by_line[1]["value_num"] == 149.3
    assert by_line[2]["value_num"] == 37.8
    assert all(f["field_type"] == "unit_price" for f in extra)


def test_synthesize_skips_when_unit_price_field_already_exists():
    cam = uuid.uuid4()
    line_to_item = {1: cam}
    bom_names = {cam: "Camera"}
    extraction = {
        "currency": "USD",
        "line_items": [{"line_no": 1, "part_name": "Camera", "unit_price": 100}],
        "fields": [
            {
                "bom_line_no": 1,
                "field_type": "unit_price",
                "value_num": 100,
                "confidence": 0.95,
            }
        ],
    }
    assert _synthesize_fields_from_line_items(extraction, line_to_item, bom_names) == []
