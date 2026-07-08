"""Unit tests for BOM bootstrap from quotation extraction."""
from __future__ import annotations

from app.ingestion.bom_bootstrap import _line_items_from_fields


def test_line_items_from_fields_fallback():
    fields = [
        {
            "bom_line_no": 1,
            "field_type": "unit_price",
            "value_num": 12.5,
            "source_snippet": "Widget A unit 12.50",
        },
        {
            "bom_line_no": 2,
            "field_type": "unit_price",
            "value_num": 7.0,
            "source_snippet": "Widget B unit 7.00",
        },
    ]
    items = _line_items_from_fields(fields)
    assert len(items) == 2
    assert items[0]["part_name"] == "Widget A unit 12.50"
